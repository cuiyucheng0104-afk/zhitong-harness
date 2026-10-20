import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, resolve, sep } from 'node:path';

// Local verification only: production HTML without hydration, or failed motion chunks.
const root = resolve('dist');
const mime = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.svg': 'image/svg+xml',
};
createServer(async (request, response) => {
  const url = new URL(request.url, 'http://127.0.0.1:5329');
  const file = resolve(
    root,
    `.${decodeURIComponent(url.pathname === '/' ? '/index.html' : url.pathname)}`,
  );
  if (!file.startsWith(`${root}${sep}`)) {
    response.writeHead(403).end();
    return;
  }
  try {
    if (file.endsWith('.js')) {
      const code = await readFile(file, 'utf8');
      if (code.includes('autoSleep:120') || file.includes('ScrollTrigger-')) {
        response.writeHead(503).end('Motion unavailable for fallback verification');
        return;
      }
    }
    let content = await readFile(file);
    if (url.searchParams.has('static')) {
      content = Buffer.from(
        content
          .toString()
          .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
          .replace(/<noscript>([\s\S]*?)<\/noscript>/g, '$1'),
      );
    }
    response
      .writeHead(200, {
        'Content-Type': mime[extname(file)] ?? 'application/octet-stream',
        'Cache-Control': 'no-store',
      })
      .end(content);
  } catch {
    response.writeHead(404).end();
  }
}).listen(5329, '127.0.0.1', () => console.log('Local fallback checks: http://127.0.0.1:5329'));
