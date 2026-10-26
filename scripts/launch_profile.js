const path = require('path');
const fs = require('fs');
const http = require('http');
const net = require('net');
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
    const upstreamPort = parseInt(this.upstreamUrl.port, 10) || 80;
    const upstreamHost = this.upstreamUrl.hostname;

    const upstreamSocket = net.connect(upstreamPort, upstreamHost, () => {
      let authHeader = '';
      if (this.upstreamUrl.username || this.upstreamUrl.password) {
        const creds = Buffer.from(`${decodeURIComponent(this.upstreamUrl.username)}:${decodeURIComponent(this.upstreamUrl.password)}`).toString('base64');
        authHeader = `Proxy-Authorization: Basic ${creds}\r\n`;
      }

      const connectReq = `CONNECT ${clientReq.url} HTTP/1.1\r\nHost: ${clientReq.url}\r\n${authHeader}Proxy-Connection: Keep-Alive\r\n\r\n`;
      upstreamSocket.write(connectReq);
    });

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

    const upstreamPort = parseInt(this.upstreamUrl.port, 10) || 80;
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

    const proxyReq = http.request(options, (proxyRes) => {
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
  const proxy = process.env.PROXY_URL;
  if (!proxy) {
    console.error('[!] Error: PROXY_URL environment variable is required (e.g. export PROXY_URL=http://user:pass@host:port)');
    process.exit(1);
  }
  const cdpPort = process.env.CDP_PORT || 9222;
  const dataDir = path.join(require('os').homedir(), '.cloakbrowser', 'profiles', 'muse_profile');

  const binary = findBinary();
  console.log(`[*] Stealth Binary: ${binary}`);
  console.log(`[*] Starting Proxy Bridge for: ${proxy}`);

  const bridge = new LocalProxyBridge(proxy);
  const bridgePort = await bridge.start();
  console.log(`[*] LocalProxyBridge listening on http://127.0.0.1:${bridgePort}`);

  const args = [
    `--user-data-dir=${dataDir}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--fingerprint=61842',
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

  console.log(`[*] Launching browser on port ${cdpPort}...`);
  const child = spawn(binary, args, { stdio: 'inherit' });

  child.on('exit', (code) => {
    bridge.stop();
    process.exit(code || 0);
  });
}

main().catch(console.error);
