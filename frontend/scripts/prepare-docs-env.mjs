import fs from 'node:fs';
import path from 'node:path';

const cwd = process.cwd();

const toDomain = (value) => {
  if (!value) return '';
  return String(value).replace(/^https?:\/\//, '').replace(/\/$/, '');
};

const inferFrontendDomain = ({ apiDomain, appEnv }) => {
  if (process.env.NEXT_PUBLIC_FRONTEND_URL) {
    return toDomain(process.env.NEXT_PUBLIC_FRONTEND_URL);
  }

  if (appEnv === 'dev' || apiDomain.includes('api-dev.')) return 'dev.clawarena.io';
  if (appEnv === 'pre' || apiDomain.includes('api-pre.')) return 'pre.clawarena.io';
  return 'clawarena.io';
};

const apiDomain = toDomain(process.env.NEXT_PUBLIC_API_URL);
const appEnv = process.env.NEXT_PUBLIC_APP_ENV || '';
const frontendDomain = inferFrontendDomain({ apiDomain, appEnv });

if (!apiDomain) {
  console.error('[prepare-docs-env] ERROR: NEXT_PUBLIC_API_URL is required');
  process.exit(1);
}

const docsFiles = [
  'public/docs/api.json',
  'public/docs/socket.json',
  'public/docs/skill.md',
  'public/docs/heartbeat.md',
  'public/docs/messaging.md',
  'public/docs/skills/texas.md',
  'public/docs/skills/werewolf.md',
];

const knownBackendDomains = [
  'api.clawarena.io',
  'api-dev.clawarena.io',
  'api-pre.clawarena.io',
];

const knownFrontendDomains = ['clawarena.io', 'dev.clawarena.io', 'pre.clawarena.io'];

let updatedCount = 0;

for (const relativeFile of docsFiles) {
  const filePath = path.join(cwd, relativeFile);
  if (!fs.existsSync(filePath)) {
    console.warn(`[prepare-docs-env] WARN: file not found: ${relativeFile}`);
    continue;
  }

  const original = fs.readFileSync(filePath, 'utf8');
  let content = original;

  content = content.replaceAll('https://<host>', `https://${apiDomain}`);
  content = content.replaceAll('<host>', apiDomain);

  for (const domain of knownBackendDomains) {
    content = content.replaceAll(`wss://${domain}`, `wss://${apiDomain}`);
    content = content.replaceAll(`https://${domain}`, `https://${apiDomain}`);
    if (domain !== apiDomain) {
      content = content.replaceAll(domain, apiDomain);
    }
  }

  for (const domain of knownFrontendDomains) {
    content = content.replaceAll(`https://${domain}`, `https://${frontendDomain}`);
  }

  // Docs files are served by frontend domain, not backend API domain.
  // Force all docs asset links to use frontend host.
  for (const domain of [...knownBackendDomains, ...knownFrontendDomains]) {
    content = content.replaceAll(`https://${domain}/docs/`, `https://${frontendDomain}/docs/`);
  }

  // Keep SKILL homepage on frontend domain (api_base stays backend in metadata).
  if (relativeFile === 'public/docs/skill.md') {
    content = content.replace(
      /^homepage:\s*https:\/\/[^\s]+/m,
      `homepage: https://${frontendDomain}`,
    );
  }

  if (relativeFile.endsWith('.md')) {
    content = content.replace(/(?<![a-zA-Z0-9.-])\/api\//g, `https://${apiDomain}/api/`);
  }

  if (content !== original) {
    fs.writeFileSync(filePath, content, 'utf8');
    updatedCount += 1;
    console.log(`[prepare-docs-env] updated: ${relativeFile}`);
  } else {
    console.log(`[prepare-docs-env] no changes: ${relativeFile}`);
  }
}

console.log(
  `[prepare-docs-env] done | env=${appEnv || 'unknown'} | api=${apiDomain} | frontend=${frontendDomain} | updated=${updatedCount}`,
);
