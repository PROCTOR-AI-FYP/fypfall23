const fs = require('fs');

let content = fs.readFileSync('src/lib/api.ts', 'utf8');

if (!content.includes("import { mockCall }")) {
  content = content.replace(
    "import {\n  Role, CaseStatus, BehaviorType, PenaltyType, AppealStatus, SessionStatus,\n} from './types';",
    "import {\n  Role, CaseStatus, BehaviorType, PenaltyType, AppealStatus, SessionStatus,\n} from './types';\nimport { mockCall } from './mock-db';"
  );
  // Also try single line if it doesn't match multiline
  content = content.replace(
    "import { Role, CaseStatus, BehaviorType, PenaltyType, AppealStatus, SessionStatus } from './types';",
    "import { Role, CaseStatus, BehaviorType, PenaltyType, AppealStatus, SessionStatus } from './types';\nimport { mockCall } from './mock-db';"
  );
}

// Fixed Regex for Windows line endings
const regex = /export async function ([a-zA-Z0-9_]+)\((.*?)\):?\s*Promise<([\s\S]*?)> \{\r?\n([\s\S]*?)\r?\n\}/g;

content = content.replace(regex, (match, funcName, argsStr, retType, body) => {
  // skip if already wrapped
  if (body.includes('mockCall(')) return match;
  // skip auth functions as per mock-db.ts
  if (['exchangeGoogleSession', 'getCurrentUser', 'logout', 'subscribeToAlerts'].includes(funcName)) return match;

  // Extract argument names safely
  const argNames = [];
  let currentArg = '';
  let depth = 0;
  for (let i = 0; i < argsStr.length; i++) {
    const char = argsStr[i];
    if (char === '{' || char === '<' || char === '[') depth++;
    else if (char === '}' || char === '>' || char === ']') depth--;
    else if (char === ',' && depth === 0) {
      if (currentArg.trim()) argNames.push(currentArg.trim().split(':')[0].split('?')[0]);
      currentArg = '';
      continue;
    }
    currentArg += char;
  }
  if (currentArg.trim()) argNames.push(currentArg.trim().split(':')[0].split('?')[0]);

  const argsList = argNames.join(', ');

  return `export async function ${funcName}(${argsStr}): Promise<${retType}> {
  try {
${body}
  } catch (e: any) {
    if (e.code === 'NETWORK_ERROR') {
      console.warn('Falling back to mock-db for ${funcName}');
      return mockCall('${funcName}', [${argsList}]);
    }
    throw e;
  }
}`;
});

fs.writeFileSync('src/lib/api.ts', content, 'utf8');
console.log('Done rewriting!');
