# Mixtral Invocation Guide - Your Council Orchestrator System

**Based on your existing implementation in Phase 05 Business Logic Extraction**

---

## Table of Contents
1. [System Overview](#system-overview)
2. [How Mixtral is Configured](#how-mixtral-is-configured)
3. [API Key Setup](#api-key-setup)
4. [How to Invoke Mixtral](#how-to-invoke-mixtral)
5. [Response Handling](#response-handling)
6. [Spawning Agents with Mixtral](#spawning-agents-with-mixtral)
7. [Structured Responses](#structured-responses)
8. [Complete Examples](#complete-examples)
9. [Debugging & Monitoring](#debugging--monitoring)

---

## System Overview

Your system uses a **Council Orchestrator** architecture where **4 LLM providers run in parallel**:

1. **Kimi** (moonshot.ai) - `kimi-k2.5`
2. **MiniMax** - `MiniMax-M2.1`
3. **DeepSeek** - `deepseek-reasoner`
4. **Mixtral** (Mistral AI) - `magistral-medium-latest`

### Key Architecture Features

```
┌─────────────────────────────────────────────────────┐
│           Council Orchestrator                      │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────┐  ┌─────────┐  ┌──────────┐  ┌─────────┐│
│  │ Kimi │  │ MiniMax │  │ DeepSeek │  │ Mixtral ││
│  └──────┘  └─────────┘  └──────────┘  └─────────┘│
│      │          │            │             │       │
│      └──────────┴────────────┴─────────────┘       │
│                      ↓                              │
│              Batch Response Parser                  │
│                      ↓                              │
│              Variance Analysis                      │
│                      ↓                              │
│           Aggregated Results (JSON)                 │
└─────────────────────────────────────────────────────┘
```

**Location in Codebase:**
- Orchestrator: `knowledge-graph/orchestration/council-orchestrator.js`
- Config: `knowledge-graph/orchestration/config.js`
- Batch Worker: `knowledge-graph/scripts/batch-agent-worker.js`
- API Key Loader: `knowledge-graph/orchestration/load-api-keys-from-keychain.js`

---

## How Mixtral is Configured

### Configuration File: `knowledge-graph/orchestration/config.js`

```javascript
export const LLM_PROVIDERS = {
  // ... other providers ...

  mixtral: {
    name: 'Mixtral',
    endpoint: 'https://api.mistral.ai/v1/chat/completions',
    model: 'magistral-medium-latest',  // NOT open-mixtral-8x7b
    apiKeyEnv: 'MIXTRAL_API_KEY',
    maxRequestsPerMinute: 60,
    maxConcurrentRequests: 3,
    timeout: 240000,  // 4 minutes (240s) for reasoning models
  },
};

export const EXTRACTION_CONFIG = {
  temperature: 1.0,        // Required for reasoning models
  maxTokens: 8000,         // Increased for verbose reasoning output
  jsonMode: true,          // Force JSON responses
  minimumSuccessfulProviders: 2,  // Need at least 2/4 to succeed
};
```

**Important Notes:**
1. **Model**: You're using `magistral-medium-latest` (Mistral's reasoning model), NOT the open-source Mixtral models
2. **Timeout**: 4 minutes because reasoning models take longer
3. **Temperature**: 1.0 required for reasoning models (not 0.7)
4. **JSON Mode**: Enabled for Mixtral in the orchestrator (lines 163-165)

---

## API Key Setup

### Option 1: macOS Keychain (Recommended - You're Using This)

**Check Current Status:**
```bash
cd knowledge-graph/orchestration
node load-api-keys-from-keychain.js
```

**Add/Update Mixtral Key:**
```bash
# Add to keychain
security add-generic-password -a "$USER" -s "mistral-api-key" -w "YOUR_MISTRAL_API_KEY"

# Verify it's stored
security find-generic-password -s "mistral-api-key" -w
```

**View All Keychain Keys:**
```bash
# List all stored API keys
security find-generic-password -s "kimi-api-key" -w
security find-generic-password -s "minimax-api-key" -w
security find-generic-password -s "deepseek-api-key" -w
security find-generic-password -s "mistral-api-key" -w
```

### Option 2: Environment Variables (Fallback)

**Temporary (current session):**
```bash
export MIXTRAL_API_KEY="your-api-key-here"
```

**Permanent (add to ~/.zshrc or ~/.bashrc):**
```bash
echo 'export MIXTRAL_API_KEY="your-api-key-here"' >> ~/.zshrc
source ~/.zshrc
```

### How Your System Loads Keys

From `config.js` (lines 82-133):

```javascript
export function loadApiKeys() {
  const keys = {};
  let missingKeys = [];

  // Try keychain first (macOS)
  const keychainServices = {
    kimi: 'kimi-api-key',
    minimax: 'minimax-api-key',
    deepseek: 'deepseek-api-key',
    mixtral: 'mistral-api-key'  // ← Service name for Mixtral
  };

  for (const [provider, serviceName] of Object.entries(keychainServices)) {
    try {
      const key = execSync(
        `security find-generic-password -s "${serviceName}" -w`,
        { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }
      ).trim();

      if (key) {
        keys[provider] = key;
        process.env[`${provider.toUpperCase()}_API_KEY`] = key;
      }
    } catch (error) {
      // Key not in keychain, will try environment variable
    }
  }

  // Fallback to environment variables
  for (const [provider, config] of Object.entries(LLM_PROVIDERS)) {
    if (!keys[provider]) {
      const key = process.env[config.apiKeyEnv];
      if (key) {
        keys[provider] = key;
      } else {
        missingKeys.push(config.apiKeyEnv);
      }
    }
  }

  return { keys, missingKeys, hasAllKeys: missingKeys.length === 0 };
}
```

---

## How to Invoke Mixtral

### 1. Using the Council Orchestrator (Recommended)

**This is how you're currently using it - all 4 providers in parallel:**

```javascript
import { CouncilOrchestrator } from './orchestration/council-orchestrator.js';

// Initialize orchestrator
const orchestrator = new CouncilOrchestrator({ verbose: true });

// Extract from a batch of modules
const batch = [
  'backend/src/models/invoice.js',
  'backend/src/services/billing.js'
];

const sourceCodeMap = {
  'backend/src/models/invoice.js': readFileSync('...', 'utf-8'),
  'backend/src/services/billing.js': readFileSync('...', 'utf-8')
};

const contextMap = {
  'backend/src/models/invoice.js': { /* metadata */ },
  'backend/src/services/billing.js': { /* metadata */ }
};

// This calls ALL 4 providers (including Mixtral) in parallel
const result = await orchestrator.extractBatch(
  batch,
  sourceCodeMap,
  contextMap,
  { dryRun: false }
);

// Results are aggregated per module
console.log('Module Results:', result.moduleResults);
console.log('Batch Stats:', result.batchStats);
```

### 2. Calling ONLY Mixtral (Single Provider)

**If you want to call Mixtral alone (not the full council):**

```javascript
import { CouncilOrchestrator } from './orchestration/council-orchestrator.js';
import { getProviderSystemPrompt, buildBatchIntentPrompt } from './orchestration/batch-prompt-builder.js';

// Initialize
const orchestrator = new CouncilOrchestrator({ verbose: true });

// Build prompts
const systemPrompt = getProviderSystemPrompt('mixtral');
const userPrompt = buildBatchIntentPrompt(modulePaths, sourceCodeMap, contextMap);

// Call ONLY Mixtral (not the full council)
const result = await orchestrator.callProviderBatchOnce(
  'mixtral',
  userPrompt,
  systemPrompt,
  {
    dryRun: false,
    moduleCount: modulePaths.length,
    modulePaths: modulePaths
  }
);

if (result.success) {
  console.log('Mixtral Response:', result.response);
  console.log('Tokens Used:', result.tokenCount);
  console.log('Latency:', result.latencyMs, 'ms');
} else {
  console.error('Mixtral Error:', result.error);
}
```

### 3. Direct API Call (Without Orchestrator)

**Raw fetch call matching your system's format:**

```javascript
import { getProviderConfig, loadApiKeys } from './orchestration/config.js';

const config = getProviderConfig('mixtral');
const { keys } = loadApiKeys();
const apiKey = keys.mixtral;

const response = await fetch(config.endpoint, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${apiKey}`
  },
  body: JSON.stringify({
    model: config.model,  // magistral-medium-latest
    messages: [
      {
        role: 'system',
        content: 'You are a business logic extraction assistant. Return only valid JSON.'
      },
      {
        role: 'user',
        content: 'Extract business rules from this code: ...'
      }
    ],
    temperature: 1.0,     // Required for reasoning models
    max_tokens: 8000,     // Your configured max
    response_format: { type: 'json_object' }  // Force JSON mode
  })
});

const data = await response.json();
const content = data.choices[0].message.content;

// Mixtral (Magistral) returns content as array of objects
let extractedText;
if (Array.isArray(content)) {
  // Find the text object (not thinking)
  const textObj = content.find(obj => obj.type === 'text');
  extractedText = textObj?.text || '';
} else {
  extractedText = content;
}

console.log('Mixtral Response:', extractedText);
console.log('Token Usage:', data.usage);
```

---

## Response Handling

### Mixtral's Response Format

**Your orchestrator handles this (lines 228-246):**

```javascript
extractContent(data, provider) {
  const rawContent = data.choices?.[0]?.message?.content;

  // Mixtral (Magistral) returns content as array of objects
  if (provider === 'mixtral' && Array.isArray(rawContent)) {
    // Find the text object (not thinking)
    const textObj = rawContent.find(obj => obj.type === 'text');
    return textObj?.text || '';
  }

  // All other providers use simple string content
  return rawContent || '';
}
```

**Example Mixtral Response Structure:**

```json
{
  "id": "chat-abc123",
  "model": "magistral-medium-latest",
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": [
          {
            "type": "thinking",
            "thinking": "Let me analyze this code..."
          },
          {
            "type": "text",
            "text": "{\"rules\": [{\"rule\": \"...\", \"type\": \"POLICY\"}]}"
          }
        ]
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 1234,
    "completion_tokens": 567,
    "total_tokens": 1801
  }
}
```

**Key Points:**
1. Magistral models return `content` as an **array of objects**
2. You need to **filter for `type === 'text'`** to get the actual response
3. The `thinking` object contains reasoning (optional, can be logged for debugging)

---

## Spawning Agents with Mixtral

### Your Batch Agent Worker Pattern

**From `batch-agent-worker.js` (lines 48-87):**

```javascript
/**
 * Extract with a single provider
 */
async function extractWithProvider(orchestrator, provider, modulePaths, sourceCodeMap, contextMap) {
  const startTime = Date.now();

  const systemPrompt = getProviderSystemPrompt(provider);
  const userPrompt = buildBatchIntentPrompt(modulePaths, sourceCodeMap, contextMap);

  const result = await orchestrator.callProviderBatchOnce(
    provider,
    userPrompt,
    systemPrompt,
    {
      dryRun: false,
      moduleCount: modulePaths.length,
      modulePaths: modulePaths
    }
  );

  const latencyMs = Date.now() - startTime;

  if (!result.success) {
    return {
      provider,
      success: false,
      error: result.error,
      latencyMs
    };
  }

  const parsed = parseBatchResponse(result.response, modulePaths.length, modulePaths);

  return {
    provider,
    success: true,
    latencyMs,
    tokenCount: result.tokenCount,
    parsed,
    successfulModules: parsed.results.length,
    failedModules: parsed.failures.length
  };
}
```

### Spawning Multiple Agents in Parallel

**Your system already does this (batch-agent-worker.js lines 134-140):**

```javascript
// Execute council (4 providers in parallel)
const providers = ['kimi', 'minimax', 'deepseek', 'mixtral'];

const results = await Promise.all(
  providers.map(provider =>
    extractWithProvider(orchestrator, provider, modulePaths, sourceCodeMap, contextMap)
  )
);
```

### Spawning ONLY Mixtral Agents (Multiple Concurrent)

**If you want to run multiple Mixtral agents concurrently:**

```javascript
import { CouncilOrchestrator } from './orchestration/council-orchestrator.js';

const orchestrator = new CouncilOrchestrator({ verbose: true });

// Multiple different batches processed by Mixtral concurrently
const batch1 = ['module1.js', 'module2.js'];
const batch2 = ['module3.js', 'module4.js'];
const batch3 = ['module5.js', 'module6.js'];

const mixtralAgents = await Promise.all([
  extractWithProvider(orchestrator, 'mixtral', batch1, sourceCodeMap1, contextMap1),
  extractWithProvider(orchestrator, 'mixtral', batch2, sourceCodeMap2, contextMap2),
  extractWithProvider(orchestrator, 'mixtral', batch3, sourceCodeMap3, contextMap3)
]);

// Analyze results
mixtralAgents.forEach((result, i) => {
  console.log(`Batch ${i + 1}:`);
  console.log(`  Success: ${result.success}`);
  console.log(`  Tokens: ${result.tokenCount}`);
  console.log(`  Latency: ${result.latencyMs}ms`);
  console.log(`  Successful Modules: ${result.successfulModules}`);
});
```

**Note:** Your rate limiter in the orchestrator will ensure you don't exceed 60 requests/minute for Mixtral.

---

## Structured Responses

### How Your System Enforces JSON

**Your orchestrator enables JSON mode for Mixtral (lines 163-165):**

```javascript
// Add JSON mode if supported (OpenAI-compatible providers)
if (EXTRACTION_CONFIG.jsonMode && ['deepseek', 'mixtral'].includes(provider)) {
  body.response_format = { type: 'json_object' };
}
```

### Your Business Logic Schema

**From your batch response parser and rule schema:**

```javascript
// Expected response format (per module)
{
  "rules": [
    {
      "rule": "Invoice must be in DRAFT state before it can be sent",
      "type": "POLICY",  // POLICY | INVARIANT | VALIDATION | WORKFLOW
      "sourceLines": [45, 52],
      "pseudoCode": "if (invoice.state !== 'DRAFT') throw error",
      "confidence": 0.9,
      "sliceSpecific": "invoice_state_machine",  // For domain pass
      "severity": "P1"  // For domain pass
    }
  ],
  "domainConcepts": [  // For domain pass
    {
      "name": "Invoice Lifecycle",
      "rules": [0, 1]  // Indices into rules array
    }
  ],
  "hiddenDependencies": [  // For dependency pass
    {
      "type": "state",
      "description": "Requires invoice to be persisted before calculating totals",
      "relatedModules": ["backend/src/models/invoice_item.js"],
      "confidence": 0.85
    }
  ]
}
```

### Parsing Mixtral's Structured Response

**Your batch response parser handles this:**

```javascript
import { parseBatchResponse } from './orchestration/batch-response-parser.js';

// Mixtral returns multiple modules in batch format:
const response = `
MODULE_1_START: backend/src/models/invoice.js
{
  "rules": [...]
}
MODULE_1_END

MODULE_2_START: backend/src/services/billing.js
{
  "rules": [...]
}
MODULE_2_END
`;

const parsed = parseBatchResponse(
  response,
  2,  // number of modules
  ['backend/src/models/invoice.js', 'backend/src/services/billing.js']
);

console.log('Results:', parsed.results);
console.log('Failures:', parsed.failures);
```

---

## Complete Examples

### Example 1: Full Council Extraction (Your Current Pattern)

```javascript
#!/usr/bin/env node
/**
 * Run full council extraction on a batch of modules
 */
import { CouncilOrchestrator } from './orchestration/council-orchestrator.js';
import { readFileSync } from 'fs';
import { join } from 'path';

async function runFullCouncilExtraction() {
  console.log('🏛️  Initializing Council Orchestrator...');

  const orchestrator = new CouncilOrchestrator({ verbose: true });

  // Define batch
  const batch = [
    'backend/src/models/invoice.js',
    'backend/src/models/person.js',
    'backend/src/services/mailer.js'
  ];

  console.log(`📦 Processing batch of ${batch.length} modules\n`);

  // Load source code
  const workboxRoot = join(process.cwd(), 'workbox');
  const sourceCodeMap = {};
  const contextMap = {};

  for (const modulePath of batch) {
    const fullPath = join(workboxRoot, modulePath);
    sourceCodeMap[modulePath] = readFileSync(fullPath, 'utf-8');
    contextMap[modulePath] = {
      linesOfCode: sourceCodeMap[modulePath].split('\n').length,
      functions: []  // Add metadata as needed
    };
  }

  // Execute council (all 4 providers in parallel)
  const startTime = Date.now();
  const result = await orchestrator.extractBatch(
    batch,
    sourceCodeMap,
    contextMap,
    { dryRun: false }
  );

  const totalTime = Date.now() - startTime;

  // Display results
  console.log('\n' + '='.repeat(80));
  console.log('COUNCIL EXTRACTION COMPLETE');
  console.log('='.repeat(80));
  console.log(`Total Time: ${totalTime}ms`);
  console.log(`Successful Modules: ${result.batchStats.successfulModules}/${result.batchStats.totalModules}`);
  console.log(`Successful Providers: ${result.batchStats.successfulProviders}/${result.batchStats.totalProviders}`);

  // Provider breakdown
  console.log('\n📊 Provider Performance:');
  for (const [provider, stats] of Object.entries(result.batchStats.providerStats)) {
    if (stats.success) {
      console.log(`  ${provider}:`);
      console.log(`    Modules: ${stats.successfulModules}/${batch.length}`);
      console.log(`    Tokens: ${stats.tokenCount}`);
      console.log(`    Latency: ${stats.latencyMs}ms`);
    } else {
      console.log(`  ${provider}: ❌ ${stats.error}`);
    }
  }

  // Per-module results
  console.log('\n📝 Module Results:');
  for (const [modulePath, moduleResult] of Object.entries(result.moduleResults)) {
    console.log(`\n  ${modulePath}:`);
    console.log(`    Providers: ${moduleResult.successCount}/4`);

    for (const providerResult of moduleResult.providerResults) {
      const ruleCount = providerResult.data?.rules?.length || 0;
      console.log(`      ${providerResult.provider}: ${ruleCount} rules (position ${providerResult.position})`);
    }
  }

  // Token usage
  console.log('\n💰 Token Usage:');
  orchestrator.displayTokenStats('Council Extraction');

  // Save results
  const outputPath = '.planning/artifacts/extraction-results.json';
  orchestrator.saveTokenStats(outputPath.replace('.json', '-tokens.json'));
  console.log(`\n💾 Results saved to ${outputPath}`);
}

runFullCouncilExtraction().catch(console.error);
```

### Example 2: Mixtral-Only Extraction

```javascript
#!/usr/bin/env node
/**
 * Run extraction with ONLY Mixtral (no council)
 */
import { CouncilOrchestrator } from './orchestration/council-orchestrator.js';
import { getProviderSystemPrompt, buildBatchIntentPrompt } from './orchestration/batch-prompt-builder.js';
import { parseBatchResponse } from './orchestration/batch-response-parser.js';
import { readFileSync } from 'fs';
import { join } from 'path';

async function runMixtralOnly() {
  console.log('🤖 Running Mixtral-only extraction...\n');

  const orchestrator = new CouncilOrchestrator({ verbose: true });

  // Single module extraction
  const modulePath = 'backend/src/models/invoice.js';
  const fullPath = join(process.cwd(), 'workbox', modulePath);
  const sourceCode = readFileSync(fullPath, 'utf-8');

  const sourceCodeMap = { [modulePath]: sourceCode };
  const contextMap = {
    [modulePath]: {
      linesOfCode: sourceCode.split('\n').length
    }
  };

  // Build prompts
  const systemPrompt = getProviderSystemPrompt('mixtral');
  const userPrompt = buildBatchIntentPrompt([modulePath], sourceCodeMap, contextMap);

  console.log('📤 Sending request to Mixtral (magistral-medium-latest)...');

  // Call Mixtral
  const startTime = Date.now();
  const result = await orchestrator.callProviderBatchOnce(
    'mixtral',
    userPrompt,
    systemPrompt,
    {
      dryRun: false,
      moduleCount: 1,
      modulePaths: [modulePath]
    }
  );
  const latency = Date.now() - startTime;

  if (!result.success) {
    console.error('❌ Mixtral extraction failed:', result.error);
    return;
  }

  console.log(`✅ Mixtral responded in ${latency}ms`);
  console.log(`💰 Tokens used: ${result.tokenCount}`);

  // Parse response
  const parsed = parseBatchResponse(result.response, 1, [modulePath]);

  if (parsed.results.length > 0) {
    const moduleResult = parsed.results[0];
    const rules = moduleResult.data?.rules || [];

    console.log(`\n📋 Extracted ${rules.length} business rules:`);
    rules.forEach((rule, i) => {
      console.log(`\n  Rule ${i + 1}:`);
      console.log(`    Type: ${rule.type}`);
      console.log(`    Description: ${rule.rule}`);
      console.log(`    Confidence: ${rule.confidence}`);
      console.log(`    Source Lines: ${rule.sourceLines?.join(', ')}`);
    });
  }

  if (parsed.failures.length > 0) {
    console.log('\n⚠️  Parsing failures:');
    parsed.failures.forEach(failure => {
      console.log(`  ${failure.modulePath}: ${failure.error}`);
    });
  }

  // Display token stats
  console.log('\n💰 Detailed Token Usage:');
  orchestrator.displayTokenStats('Mixtral Extraction');
}

runMixtralOnly().catch(console.error);
```

### Example 3: Test Mixtral Configuration

```javascript
#!/usr/bin/env node
/**
 * Test Mixtral API connectivity and configuration
 */
import { getProviderConfig, loadApiKeys } from './orchestration/config.js';

async function testMixtral() {
  console.log('🔍 Testing Mixtral Configuration...\n');

  // Check API key
  const { keys, missingKeys } = loadApiKeys();

  if (!keys.mixtral) {
    console.error('❌ MIXTRAL_API_KEY not found');
    console.log('\nTo add via keychain:');
    console.log('  security add-generic-password -a "$USER" -s "mistral-api-key" -w "YOUR_API_KEY"');
    console.log('\nOr set environment variable:');
    console.log('  export MIXTRAL_API_KEY="YOUR_API_KEY"');
    return;
  }

  console.log('✅ API key loaded:', keys.mixtral.substring(0, 10) + '...');

  // Get config
  const config = getProviderConfig('mixtral');
  console.log('\n📋 Configuration:');
  console.log(`  Endpoint: ${config.endpoint}`);
  console.log(`  Model: ${config.model}`);
  console.log(`  Max Requests/Min: ${config.maxRequestsPerMinute}`);
  console.log(`  Timeout: ${config.timeout}ms`);

  // Test API call
  console.log('\n📡 Testing API connectivity...');

  const response = await fetch(config.endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${keys.mixtral}`
    },
    body: JSON.stringify({
      model: config.model,
      messages: [
        {
          role: 'user',
          content: 'Say "API test successful" and nothing else.'
        }
      ],
      temperature: 1.0,
      max_tokens: 50
    })
  });

  if (!response.ok) {
    console.error(`❌ API call failed: HTTP ${response.status}`);
    const errorText = await response.text();
    console.error(errorText);
    return;
  }

  const data = await response.json();

  // Extract content (handle array format)
  let content = data.choices[0].message.content;
  if (Array.isArray(content)) {
    const textObj = content.find(obj => obj.type === 'text');
    content = textObj?.text || '';
  }

  console.log('✅ API call successful!');
  console.log(`Response: ${content}`);
  console.log(`Tokens used: ${data.usage.total_tokens}`);
  console.log(`Model: ${data.model}`);

  console.log('\n🎉 Mixtral is properly configured and working!');
}

testMixtral().catch(console.error);
```

---

## Debugging & Monitoring

### 1. Enable Verbose Logging

```javascript
const orchestrator = new CouncilOrchestrator({ verbose: true });
```

This will log:
- API calls and responses
- Rate limiting waits
- Retry attempts
- Parsing issues

### 2. Monitor Token Usage

**Your orchestrator has built-in token tracking:**

```javascript
// Display token stats in console
orchestrator.displayTokenStats('Extraction Run');

// Save to file
orchestrator.saveTokenStats('.planning/artifacts/token-usage.json');

// Get programmatic summary
const summary = orchestrator.getTokenSummary();
console.log('Total Tokens:', summary.totalTokens);
console.log('Total Cost:', summary.totalCost);
console.log('Per Provider:', summary.byProvider);
```

### 3. Check Rate Limiter Status

```javascript
const stats = orchestrator.getStats();
console.log('Rate Limiter Stats:', stats.rateLimiter);
console.log('Config:', stats.config);
```

### 4. Analyze Batch Results

**From your batch agent worker pattern:**

```javascript
// Per-module variance analysis
moduleAnalysis.forEach(module => {
  console.log(`\n${module.modulePath}:`);
  console.log(`  Baseline Rules: ${module.baseline}`);
  console.log(`  Avg Extracted: ${module.avgRuleCount}`);
  console.log(`  Std Dev: ${module.variance.stdDev.toFixed(2)}`);
  console.log(`  Range: [${module.variance.range.join(', ')}]`);
  console.log(`  Agreement Rate: ${(module.variance.agreementRate * 100).toFixed(0)}%`);
  console.log(`  Recall: ${(module.recall * 100).toFixed(0)}%`);
});
```

### 5. Debug Response Parsing Issues

**If Mixtral responses aren't parsing correctly:**

```javascript
// Log raw response
if (orchestrator.verbose) {
  console.log('Raw Mixtral Response:');
  console.log(result.response.substring(0, 1000) + '...');
}

// Test response extraction
const content = orchestrator.extractContent(data, 'mixtral');
console.log('Extracted Content:', content);

// Test batch parsing
const parsed = parseBatchResponse(content, moduleCount, modulePaths);
console.log('Parsed Results:', parsed.results.length);
console.log('Parsing Failures:', parsed.failures);
```

### 6. Common Issues & Solutions

**Issue: Mixtral timeout errors**
```javascript
// Increase timeout in config.js
mixtral: {
  timeout: 300000,  // 5 minutes instead of 4
}
```

**Issue: Rate limit exceeded**
```javascript
// Check current rate limit status
const canMakeRequest = orchestrator.rateLimiter.canMakeRequest('mixtral');
if (!canMakeRequest) {
  console.log('Rate limit reached, waiting...');
  await orchestrator.rateLimiter.waitIfNeeded('mixtral');
}
```

**Issue: JSON parsing errors**
```javascript
// Enable JSON mode is already on for Mixtral in your config
// If still getting non-JSON responses, add stricter prompt:
const systemPrompt = `You are a business logic extraction assistant.
You MUST return ONLY valid JSON.
Do NOT include any text before or after the JSON object.`;
```

**Issue: API key not found**
```bash
# Verify keychain entry
security find-generic-password -s "mistral-api-key" -w

# If not found, add it
security add-generic-password -a "$USER" -s "mistral-api-key" -w "YOUR_KEY"

# Or use environment variable
export MIXTRAL_API_KEY="YOUR_KEY"
```

---

## Summary: How to Invoke Mixtral in Your System

### Quick Reference

1. **Full Council (4 providers including Mixtral):**
   ```javascript
   const orchestrator = new CouncilOrchestrator({ verbose: true });
   const result = await orchestrator.extractBatch(batch, sourceCodeMap, contextMap);
   ```

2. **Mixtral Only:**
   ```javascript
   const result = await orchestrator.callProviderBatchOnce(
     'mixtral',
     userPrompt,
     systemPrompt,
     { dryRun: false, moduleCount: n, modulePaths: paths }
   );
   ```

3. **Get API Key:**
   ```javascript
   const { keys } = loadApiKeys();
   const mixtralKey = keys.mixtral;
   ```

4. **Parse Response:**
   ```javascript
   const content = orchestrator.extractContent(data, 'mixtral');
   const parsed = parseBatchResponse(content, moduleCount, modulePaths);
   ```

5. **Monitor Usage:**
   ```javascript
   orchestrator.displayTokenStats('Run Name');
   orchestrator.saveTokenStats('path/to/tokens.json');
   ```

### Files to Reference

- **Main orchestrator**: `knowledge-graph/orchestration/council-orchestrator.js`
- **Configuration**: `knowledge-graph/orchestration/config.js`
- **Batch worker**: `knowledge-graph/scripts/batch-agent-worker.js`
- **Prompt builder**: `knowledge-graph/orchestration/batch-prompt-builder.js`
- **Response parser**: `knowledge-graph/orchestration/batch-response-parser.js`
- **API key loader**: `knowledge-graph/orchestration/load-api-keys-from-keychain.js`

---

**Last Updated:** February 2026 (based on your Phase 05 implementation)
