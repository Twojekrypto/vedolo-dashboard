const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const url = require('url');

const PORT = 8899;
const STATIC_DIR = __dirname;

// MIME types for static files
const MIME = {
    '.html': 'text/html',
    '.css': 'text/css',
    '.js': 'application/javascript',
    '.json': 'application/json',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.woff2': 'font/woff2',
    '.woff': 'font/woff',
    '.ttf': 'font/ttf',
};

// Proxy whitelist — only these origins are allowed
const ALLOWED_ORIGINS = [
    'https://api.coingecko.com',
    'https://api.llama.fi',
];

function proxyRequest(targetUrl, res) {
    const parsed = url.parse(targetUrl);
    const options = {
        hostname: parsed.hostname,
        port: 443,
        path: parsed.path,
        method: 'GET',
        headers: {
            'User-Agent': 'VeDOLO-Dashboard/1.0',
            'Accept': 'application/json',
        },
    };

    const proxyReq = https.request(options, (proxyRes) => {
        let body = '';
        proxyRes.on('data', (chunk) => body += chunk);
        proxyRes.on('end', () => {
            res.writeHead(proxyRes.statusCode, {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'public, max-age=30',
            });
            res.end(body);
        });
    });

    proxyReq.on('error', (e) => {
        console.error('Proxy error:', e.message);
        res.writeHead(502, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Proxy failed', message: e.message }));
    });

    proxyReq.setTimeout(15000, () => {
        proxyReq.destroy();
        res.writeHead(504, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Upstream timeout' }));
    });

    proxyReq.end();
}

function serveStatic(filePath, res) {
    const ext = path.extname(filePath).toLowerCase();
    const mime = MIME[ext] || 'application/octet-stream';

    fs.readFile(filePath, (err, data) => {
        if (err) {
            res.writeHead(404, { 'Content-Type': 'text/plain' });
            res.end('Not found');
            return;
        }
        res.writeHead(200, { 'Content-Type': mime });
        res.end(data);
    });
}

const server = http.createServer((req, res) => {
    const parsed = url.parse(req.url, true);
    const pathname = parsed.pathname;

    // --- API Proxy ---
    if (pathname === '/api/proxy') {
        const targetUrl = parsed.query.url;
        if (!targetUrl) {
            res.writeHead(400, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Missing ?url= parameter' }));
            return;
        }

        // Security: only allow whitelisted origins
        const allowed = ALLOWED_ORIGINS.some(origin => targetUrl.startsWith(origin));
        if (!allowed) {
            res.writeHead(403, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'URL not in whitelist' }));
            return;
        }

        console.log(`[proxy] ${targetUrl}`);
        proxyRequest(targetUrl, res);
        return;
    }

    // --- Static files ---
    let filePath = path.join(STATIC_DIR, pathname === '/' ? 'index.html' : pathname);
    filePath = path.resolve(filePath);

    // Security: prevent path traversal
    if (!filePath.startsWith(STATIC_DIR)) {
        res.writeHead(403, { 'Content-Type': 'text/plain' });
        res.end('Forbidden');
        return;
    }

    serveStatic(filePath, res);
});

server.listen(PORT, () => {
    console.log(`\n  🚀 VeDOLO Dashboard Server`);
    console.log(`  ├─ Static:  http://localhost:${PORT}/`);
    console.log(`  ├─ Proxy:   http://localhost:${PORT}/api/proxy?url=...`);
    console.log(`  └─ Allowed: ${ALLOWED_ORIGINS.join(', ')}\n`);
});
