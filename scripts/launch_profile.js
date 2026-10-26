const crypto = require('crypto');
const path = require('path');
const fs = require('fs');
const http = require('http');
const https = require('https');
const net = require('net');
const tls = require('tls');
const { spawn } = require('child_process');
const { URL } = require('url');

class LocalProxyBridge {
  constructor(upstreamProxyUrl) {
    this.upstreamUrl = new URL(upstreamProxyUrl);
    this.server = null;
    this.port = 0;
  }

  async start() {
    return new Promise((resolve, reject) => {
      this.server = http.createServer((clientReq, clientRes) => {
        this.handleHttp(clientReq, clientRes);
      });

      this.server.on('connect', (clientReq, clientSocket, head) => {
        this.handleConnect(clientReq, clientSocket, head);
      });

      this.server.on('error', reject);

      this.server.listen(0, '127.0.0.1', () => {
        this.port = this.server.address().port;
        resolve(this.port);
      });
    });
  }

  handleConnect(clientReq, clientSocket, head) {
    const secure = this.upstreamUrl.protocol === 'https:';
    const upstreamPort = parseInt(this.upstreamUrl.port, 10) || (secure ? 443 : 80);
    const upstreamHost = this.upstreamUrl.hostname;

    const onConnect = () => {
      let authHeader = '';
      if (this.upstreamUrl.username || this.upstreamUrl.password) {
        const creds = Buffer.from(`${decodeURIComponent(this.upstreamUrl.username)}:${decodeURIComponent(this.upstreamUrl.password)}`).toString('base64');
        authHeader = `Proxy-Authorization: Basic ${creds}\r\n`;
      }

      const connectReq = `CONNECT ${clientReq.url} HTTP/1.1\r\nHost: ${clientReq.url}\r\n${authHeader}Proxy-Connection: Keep-Alive\r\n\r\n`;
      upstreamSocket.write(connectReq);
    };

    const upstreamSocket = secure
      ? tls.connect({ port: upstreamPort, host: upstreamHost, servername: upstreamHost }, onConnect)
      : net.connect(upstreamPort, upstreamHost, onConnect);

    let established = false;
    let buffer = Buffer.alloc(0);

    upstreamSocket.on('data', (chunk) => {
      if (!established) {
        buffer = Buffer.concat([buffer, chunk]);
        const headerEnd = buffer.indexOf('\r\n\r\n');
        if (headerEnd !== -1) {
          const statusLine = buffer.toString('utf-8', 0, buffer.indexOf('\r\n'));
          if (statusLine.includes('200')) {
            established = true;
            clientSocket.write('HTTP/1.1 200 Connection Established\r\n\r\n');
            const remainder = buffer.slice(headerEnd + 4);
            if (remainder.length > 0) clientSocket.write(remainder);
            if (head && head.length > 0) upstreamSocket.write(head);
            upstreamSocket.pipe(clientSocket);
            clientSocket.pipe(upstreamSocket);
          } else {
            clientSocket.write(`HTTP/1.1 502 Bad Gateway\r\n\r\n`);
            clientSocket.end();
            upstreamSocket.end();
          }
        }
      }
    });

    clientSocket.on('error', () => upstreamSocket.destroy());
    upstreamSocket.on('error', () => clientSocket.destroy());
  }

  handleHttp(clientReq, clientRes) {
    // Intercept single-word probes
    const host = clientReq.headers.host || '';
    if (!host.includes('.')) {
      clientRes.writeHead(302, { Location: `https://www.google.com/search?q=${encodeURIComponent(host)}` });
      clientRes.end();
      return;
    }

    const secure = this.upstreamUrl.protocol === 'https:';
    const transport = secure ? https : http;
    const upstreamPort = parseInt(this.upstreamUrl.port, 10) || (secure ? 443 : 80);
    const upstreamHost = this.upstreamUrl.hostname;

    const options = {
      hostname: upstreamHost,
      port: upstreamPort,
      path: clientReq.url,
      method: clientReq.method,
      headers: { ...clientReq.headers },
    };

    if (this.upstreamUrl.username || this.upstreamUrl.password) {
      const creds = Buffer.from(`${decodeURIComponent(this.upstreamUrl.username)}:${decodeURIComponent(this.upstreamUrl.password)}`).toString('base64');
      options.headers['Proxy-Authorization'] = `Basic ${creds}`;
    }

    const proxyReq = transport.request(options, (proxyRes) => {
      clientRes.writeHead(proxyRes.statusCode, proxyRes.headers);
      proxyRes.pipe(clientRes, { end: true });
    });

    clientReq.pipe(proxyReq, { end: true });
    proxyReq.on('error', () => {
      clientRes.writeHead(502);
      clientRes.end('Bad gateway');
    });
  }

  stop() {
    if (this.server) this.server.close();
  }
}

function findBinary() {
  const base = path.join(require('os').homedir(), '.cloakbrowser');
  if (fs.existsSync(base)) {
    for (const d of fs.readdirSync(base)) {
      if (d.startsWith('chromium-')) {
        const exe = path.join(base, d, 'chrome.exe');
        if (fs.existsSync(exe)) return exe;
      }
    }
  }
  return 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
}

async function main() {
  let proxy = process.env.PROXY_URL;

  // If a proxies.txt list is present, pick a proxy from the pool to rotate across endpoints
  const proxiesFile = path.join(__dirname, '..', 'proxies.txt');
  if (fs.existsSync(proxiesFile)) {
    const list = fs.readFileSync(proxiesFile, 'utf-8')
      .split(/\r?\n/)
      .map(l => l.trim())
      .filter(l => l && !l.startsWith('#'));
    if (list.length > 0) {
      const chosen = list[Math.floor(Math.random() * list.length)];
      const parts = chosen.split(':');
      if (parts.length === 4) {
        // host:port:user:pass -> URL format
        proxy = `http://${parts[2]}:${parts[3]}@${parts[0]}:${parts[1]}`;
      } else if (chosen.startsWith('http://') || chosen.startsWith('https://')) {
        proxy = chosen;
      }
    }
  }

  if (!proxy) {
    console.error('[!] Error: PROXY_URL environment variable or proxies.txt is required');
    process.exit(1);
  }

  // Rotate sticky session only for rotating residential proxies (e.g., GeoNode, BrightData)
  // that support session tokens in the username. For static proxies (like Webshare),
  // preserve the original credentials intact.
  const supportsSession = proxy.includes('geonode') || proxy.includes('-session-') || proxy.includes('brightdata') || proxy.includes('oxylabs');
  if (supportsSession && process.env.PROXY_SESSION) {
    const session = process.env.PROXY_SESSION;
    proxy = proxy.replace(/^(https?:\/\/)([^@]+)@/, (m, scheme, userinfo) => {
      const [user, pass] = userinfo.split(/:(.*)/, 2);
      const base = user.replace(/-session-[^-]+-?$/, '');
      return `${scheme}${base}-session-${session}:${pass}@`;
    });
    console.log(`[*] Sticky Residential Session: ${session}`);
  }

  const cdpPort = process.env.CDP_PORT || 9222;
  const profile = process.env.PROFILE_NAME || `profile_${crypto.randomBytes(4).toString('hex')}`;
  const dataDir = path.join(require('os').homedir(), '.cloakbrowser', 'profiles', profile);

  // Generate dynamic random fingerprint seed if none is specified
  const fpSeed = process.env.FINGERPRINT || crypto.randomInt(100000, 999999).toString();

  const binary = findBinary();
  console.log(`[*] Stealth Binary: ${binary}`);
  console.log(`[*] Profile Directory: ${dataDir}`);
  console.log(`[*] Dynamic Fingerprint Seed: ${fpSeed}`);
  console.log(`[*] Starting Proxy Bridge for: ${proxy}`);

  const bridge = new LocalProxyBridge(proxy);
  const bridgePort = await bridge.start();
  console.log(`[*] LocalProxyBridge listening on http://127.0.0.1:${bridgePort}`);

  const args = [
    `--user-data-dir=${dataDir}`,
    '--no-first-run',
    '--no-default-browser-check',
    `--fingerprint=${fpSeed}`,
    '--fingerprint-platform=windows',
    '--fingerprint-taskbar-height=48',
    '--fingerprint-windows-font-metrics',
    '--enable-features=MediaRouter',
    '--fingerprint-noise=false',
    `--proxy-server=http://127.0.0.1:${bridgePort}`,
    '--webrtc-ip-handling-policy=disable_non_proxied_udp',
    '--enforce-webrtc-ip-permission-check',
    `--remote-debugging-port=${cdpPort}`,
    'https://muse.ai'
  ];

  // Pick realistic desktop resolutions
  const desktopResolutions = ['1920,1080', '1536,864', '1680,1050', '1440,900'];
  const chosenResolution = process.env.WINDOW_SIZE || desktopResolutions[Math.floor(Math.random() * desktopResolutions.length)];

  // Opt-in headless. New headless keeps the Windows persona intact, which the
  // legacy --headless=old mode does not.
  if (process.env.HEADLESS === '1' || process.env.HEADLESS === 'true') {
    args.unshift('--headless=new');
    args.unshift(`--window-size=${chosenResolution}`);
    args.unshift('--disable-gpu');
  } else {
    args.unshift(`--window-size=${chosenResolution}`);
  }

  console.log(`[*] Launching browser on port ${cdpPort}${process.env.HEADLESS === '1' || process.env.HEADLESS === 'true' ? ' (headless)' : ''}...`);
  const child = spawn(binary, args, { stdio: 'inherit' });

  child.on('exit', (code) => {
    bridge.stop();
    process.exit(code || 0);
  });
}

main().catch(console.error);
