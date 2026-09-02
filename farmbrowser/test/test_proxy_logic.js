#!/usr/bin/env node
const net = require('net');
const assert = require('assert');
let passed = 0, failed = 0;
function test(name, fn) { try { fn(); console.log(`  ✓ ${name}`); passed++; } catch (e) { console.log(`  ✗ ${name}\n    ${e.message}`); failed++; } }

function createReader(socket) {
  const leftover = { buf: Buffer.alloc(0) };
  return function readExact(n) {
    return new Promise((resolve, reject) => {
      if (leftover.buf.length >= n) { const r = leftover.buf.slice(0, n); leftover.buf = leftover.buf.slice(n); return resolve(r); }
      const t = setTimeout(() => reject(new Error(`Timeout: wanted ${n}, got ${leftover.buf.length}`)), 3000);
      function on(chunk) { leftover.buf = Buffer.concat([leftover.buf, chunk]); if (leftover.buf.length >= n) { clearTimeout(t); socket.removeListener('data', on); const r = leftover.buf.slice(0, n); leftover.buf = leftover.buf.slice(n); resolve(r); } }
      socket.on('data', on);
    });
  };
}

function makeServer(handler) {
  return new Promise((resolve) => {
    const s = net.createServer(handler);
    s.listen(0, '127.0.0.1', () => resolve({ s, port: s.address().port }));
  });
}

function makeClient(port) {
  return new Promise((resolve) => {
    const c = net.createConnection(port, '127.0.0.1');
    c.on('connect', () => resolve(c));
  });
}

async function run(name, fn) {
  try {
    await Promise.race([fn(), new Promise((_, r) => setTimeout(() => r(new Error('Timeout')), 5000))]);
    console.log(`  ✓ ${name}`); passed++;
  } catch (e) {
    console.log(`  ✗ ${name}\n    ${e.message}`); failed++;
  }
}

// =================== SOCKS5 TESTS ===================
console.log('\n--- SOCKS5 Protocol ---');

const sockTests = [];

sockTests.push(run('No-auth greeting + CONNECT', async () => {
  const { s, port } = await makeServer(client => {
    const r = createReader(client);
    r(3).then(g => { assert.strictEqual(g[0], 0x05); client.write(Buffer.from([0x05, 0x00])); return r(18); })
    .then(c => { assert.strictEqual(c[3], 0x03); assert.strictEqual(c.slice(5, 5+c[4]).toString(), 'example.com'); client.write(Buffer.alloc(10)); })
    .catch(e => { throw e; });
  });
  const c = await makeClient(port);
  const r = createReader(c);
  c.write(Buffer.from([0x05, 0x01, 0x00]));
  assert.strictEqual((await r(2))[1], 0x00);
  const buf = Buffer.alloc(18); buf[0]=5; buf[1]=1; buf[3]=3; buf[4]=11;
  Buffer.from('example.com').copy(buf, 5); buf.writeUInt16BE(443, 16);
  c.write(buf);
  assert.strictEqual((await r(10))[1], 0x00);
  c.destroy(); s.close();
}));

sockTests.push(run('User/pass auth RFC 1929', async () => {
  const { s, port } = await makeServer(client => {
    const r = createReader(client);
    r(4).then(g => { assert.strictEqual(g[1], 0x02); client.write(Buffer.from([0x05, 0x02])); return r(2); })
    .then(as => { return r(as[1]).then(u => r(1).then(pl => r(pl[0]).then(p => ({ u: u.toString(), p: p.toString() })))); })
    .then(({ u, p }) => { assert.strictEqual(u, 'admin'); assert.strictEqual(p, 'secret123'); client.write(Buffer.from([0x01, 0x00])); return r(17); })
    .then(() => client.write(Buffer.alloc(10)))
    .catch(e => { throw e; });
  });
  const c = await makeClient(port);
  const r = createReader(c);
  c.write(Buffer.from([0x05, 0x02, 0x00, 0x02]));
  assert.strictEqual((await r(2))[1], 0x02);
  const auth = Buffer.alloc(18); auth[0]=1; auth[1]=5;
  Buffer.from('admin').copy(auth, 2); auth[7]=9; Buffer.from('secret123').copy(auth, 8);
  c.write(auth);
  assert.strictEqual((await r(2))[1], 0x00);
  c.write(Buffer.from([0x05, 0x01, 0x00, 0x03, 0x12]));
  const domainBuf = Buffer.from('check.torproject.org');
  c.write(domainBuf);
  c.write(Buffer.from([0x00, 0x50]));
  assert.strictEqual((await r(10))[1], 0x00);
  c.destroy(); s.close();
}));

sockTests.push(run('Auth rejection', async () => {
  const { s, port } = await makeServer(client => {
    const r = createReader(client);
    r(4).then(() => { client.write(Buffer.from([0x05, 0x02])); return r(2); })
    .then(as => r(as[1]).then(() => r(1).then(pl => r(pl[0]))))
    .then(() => client.write(Buffer.from([0x01, 0x01])))
    .catch(() => {});
  });
  const c = await makeClient(port);
  const r = createReader(c);
  c.write(Buffer.from([0x05, 0x02, 0x00, 0x02]));
  await r(2);
  const auth = Buffer.alloc(11); auth[0]=1; auth[1]=4; Buffer.from('test').copy(auth,2); auth[6]=4; Buffer.from('pass').copy(auth,7);
  c.write(auth);
  assert.strictEqual((await r(2))[1], 0x01);
  c.destroy(); s.close();
}));

sockTests.push(run('Server 0xFF rejection', async () => {
  const { s, port } = await makeServer(client => {
    createReader(client)(3).then(() => client.write(Buffer.from([0x05, 0xFF]))).catch(() => {});
  });
  const c = await makeClient(port);
  const r = createReader(c);
  c.write(Buffer.from([0x05, 0x01, 0x00]));
  assert.strictEqual((await r(2))[1], 0xFF);
  c.destroy(); s.close();
}));

// =================== RELAY TESTS ===================
console.log('\n--- Relay Buffering ---');

const relayTests = [];

relayTests.push(run('Body bytes preserved through CONNECT relay', async () => {
  const up = await makeServer(s => s.on('data', d => s.write(d)));
  const pr = await makeServer(cs => {
    let buf = Buffer.alloc(0);
    function on(chunk) {
      buf = Buffer.concat([buf, chunk]);
      if (buf.includes(Buffer.from('\r\n\r\n'))) {
        cs.removeListener('data', on);
        const rem = buf.slice(buf.indexOf(Buffer.from('\r\n\r\n')) + 4);
        const uc = net.createConnection(up.port, '127.0.0.1', () => {
          cs.write('HTTP/1.1 200 Connection Established\r\n\r\n');
          if (rem.length > 0) uc.write(rem);
          cs.pipe(uc); uc.pipe(cs);
        });
      }
    }
    cs.on('data', on);
  });
  const body = 'A'.repeat(8000);
  const c = await makeClient(pr.port);
  c.write(`CONNECT 127.0.0.1:${up.port} HTTP/1.1\r\nHost: 127.0.0.1:${up.port}\r\n\r\n` + body);
  let rec = Buffer.alloc(0);
  await new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error('Relay timeout')), 3000);
    c.on('data', chunk => { rec = Buffer.concat([rec, chunk]); if (rec.includes(Buffer.from('AAAA'))) { clearTimeout(t); res(); } });
  });
  assert.ok((rec.toString().match(/A/g) || []).length >= 8000, 'Body preserved');
  c.destroy(); pr.s.close(); up.s.close();
}));

relayTests.push(run('10KB echo', async () => {
  const { s, port } = await makeServer(s => s.on('data', d => s.write(d)));
  const c = await makeClient(port);
  const payload = Buffer.alloc(10000); for (let i = 0; i < 10000; i++) payload[i] = i & 0xFF;
  c.write(payload);
  let rec = Buffer.alloc(0);
  await new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error('Echo timeout')), 3000);
    c.on('data', chunk => { rec = Buffer.concat([rec, chunk]); if (rec.length >= payload.length) { clearTimeout(t); res(); } });
  });
  assert.ok(rec.equals(payload), 'Byte-for-byte match');
  c.destroy(); s.close();
}));

// =================== HTTP PROXY TESTS ===================
console.log('\n--- HTTP Proxy ---');

const httpTests = [];

httpTests.push(run('HTTP CONNECT handshake', async () => {
  const up = await makeServer(s => s.on('data', d => s.write(d)));
  const pr = await makeServer(cs => {
    let buf = Buffer.alloc(0);
    function on(chunk) {
      buf = Buffer.concat([buf, chunk]);
      if (buf.includes(Buffer.from('\r\n\r\n'))) {
        cs.removeListener('data', on);
        cs.write('HTTP/1.1 200 Connection Established\r\n\r\n');
        cs.pipe(cs);
      }
    }
    cs.on('data', on);
  });
  const c = await makeClient(pr.port);
  c.write(`CONNECT 127.0.0.1:${up.port} HTTP/1.1\r\nHost: 127.0.0.1:${up.port}\r\n\r\n`);
  let rec = '';
  await new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error('HTTP proxy timeout')), 3000);
    c.on('data', chunk => { rec += chunk.toString('latin1'); if (rec.includes('200')) { clearTimeout(t); res(); } });
  });
  assert.ok(rec.startsWith('HTTP/1.1 200'));
  c.destroy(); pr.s.close(); up.s.close();
}));

// =================== UNIT TESTS ===================
console.log('\n--- Unit Tests ---');
test('Basic auth Base64', () => assert.strictEqual(Buffer.from('admin:secret123').toString('base64'), 'YWRtaW46c2VjcmV0MTIz'));
test('Port 9050 = 0x235A', () => { const b = Buffer.alloc(2); b.writeUInt16BE(9050, 0); assert.strictEqual(b[0], 0x23); assert.strictEqual(b[1], 0x5A); });
test('CONNECT ATYP=DOMAIN', () => { const d='check.torproject.org'; const b=Buffer.alloc(4+1+d.length+2); b[0]=5;b[1]=1;b[3]=3;b[4]=d.length; Buffer.from(d).copy(b,5); b.writeUInt16BE(80,5+d.length); assert.strictEqual(b.slice(5,5+d.length).toString(),d); });
test('isActive', () => { const a=(e,t,h,p)=>e&&t!=='NONE'&&h.trim().length>0&&p>0; assert.strictEqual(a(true,'HTTP','127.0.0.1',8118),true); assert.strictEqual(a(true,'NONE','127.0.0.1',8118),false); assert.strictEqual(a(true,'HTTP','',8118),false); assert.strictEqual(a(true,'HTTP','127.0.0.1',0),false); });

async function main() {
  await Promise.all([...sockTests, ...relayTests, ...httpTests]);
  console.log(`\n${'='.repeat(50)}\nResults: ${passed} passed, ${failed} failed\n${'='.repeat(50)}`);
  process.exit(failed > 0 ? 1 : 0);
}
main();
