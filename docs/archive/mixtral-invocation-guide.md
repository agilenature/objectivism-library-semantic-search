# Comprehensive Guide to Invoking Mixtral

## Table of Contents
1. [Overview](#overview)
2. [Getting API Credentials](#getting-api-credentials)
3. [Installation & Setup](#installation--setup)
4. [Basic Invocation](#basic-invocation)
5. [Spawning an Agent](#spawning-an-agent)
6. [Structured Responses](#structured-responses)
7. [Advanced Features](#advanced-features)
8. [Complete Examples](#complete-examples)

---

## Overview

**Mixtral** is a high-performance mixture-of-experts (MoE) language model created by Mistral AI. The flagship version, **Mixtral 8x7B**, uses 8 expert networks but only activates 2 per token, making it efficient while maintaining high quality.

**Available Models:**
- `mistral-small-latest` - Fast, cost-effective
- `mistral-medium-latest` - Balanced performance
- `mistral-large-latest` - Most capable
- `open-mixtral-8x7b` - Open Mixtral 8x7B
- `open-mixtral-8x22b` - Open Mixtral 8x22B

---

## Getting API Credentials

### Step 1: Create a Mistral AI Account
```bash
# Visit: https://console.mistral.ai/
# Click "Sign Up" and create an account
```

### Step 2: Generate API Key
```bash
# 1. Log in to https://console.mistral.ai/
# 2. Navigate to "API Keys" in the left sidebar
# 3. Click "Create new key"
# 4. Name your key (e.g., "mixtral-integration")
# 5. Copy the key immediately (it won't be shown again)
```

### Step 3: Store API Key Securely
```bash
# Option 1: Environment variable (recommended)
export MISTRAL_API_KEY="your-api-key-here"

# Option 2: .env file
echo "MISTRAL_API_KEY=your-api-key-here" >> .env

# Option 3: Secure key manager (e.g., macOS Keychain)
security add-generic-password -a "$USER" -s mistral-api-key -w "your-api-key-here"
```

---

## Installation & Setup

### Python Setup

```bash
# Install the official Mistral AI client
pip install mistralai

# Install additional dependencies for async and structured outputs
pip install mistralai python-dotenv pydantic asyncio aiohttp
```

### Node.js Setup

```bash
# Install the official Mistral AI client
npm install @mistralai/mistralai

# Install additional dependencies
npm install dotenv
```

### Environment Configuration

**Create `.env` file:**
```bash
MISTRAL_API_KEY=your_actual_api_key_here
MISTRAL_MODEL=open-mixtral-8x7b
```

---

## Basic Invocation

### Python: Direct API Call

```python
#!/usr/bin/env python3
"""
Basic Mixtral invocation example
"""
import os
from mistralai import Mistral

# Load API key
api_key = os.environ.get("MISTRAL_API_KEY")
if not api_key:
    raise ValueError("MISTRAL_API_KEY environment variable not set")

# Initialize client
client = Mistral(api_key=api_key)

# Define the prompt
prompt = "Explain quantum computing in simple terms."

# Invoke Mixtral
response = client.chat.complete(
    model="open-mixtral-8x7b",
    messages=[
        {
            "role": "user",
            "content": prompt
        }
    ]
)

# Extract the response
result = response.choices[0].message.content
print(f"Response: {result}")

# Access metadata
print(f"\nTokens used: {response.usage.total_tokens}")
print(f"Model: {response.model}")
print(f"Finish reason: {response.choices[0].finish_reason}")
```

### Python: With Streaming

```python
#!/usr/bin/env python3
"""
Mixtral invocation with streaming responses
"""
import os
from mistralai import Mistral

api_key = os.environ["MISTRAL_API_KEY"]
client = Mistral(api_key=api_key)

# Stream the response
stream = client.chat.stream(
    model="open-mixtral-8x7b",
    messages=[
        {"role": "user", "content": "Write a short story about AI."}
    ]
)

print("Streaming response:")
for chunk in stream:
    if chunk.data.choices[0].delta.content:
        print(chunk.data.choices[0].delta.content, end="", flush=True)

print("\n")
```

### Node.js: Direct API Call

```javascript
#!/usr/bin/env node
/**
 * Basic Mixtral invocation example (Node.js)
 */
import Mistral from '@mistralai/mistralai';
import dotenv from 'dotenv';

// Load environment variables
dotenv.config();

// Initialize client
const apiKey = process.env.MISTRAL_API_KEY;
if (!apiKey) {
    throw new Error('MISTRAL_API_KEY environment variable not set');
}

const client = new Mistral({ apiKey });

// Define the prompt
const prompt = "Explain quantum computing in simple terms.";

// Invoke Mixtral
async function invokemixtral() {
    const response = await client.chat.complete({
        model: 'open-mixtral-8x7b',
        messages: [
            {
                role: 'user',
                content: prompt
            }
        ]
    });

    // Extract the response
    const result = response.choices[0].message.content;
    console.log(`Response: ${result}`);

    // Access metadata
    console.log(`\nTokens used: ${response.usage.totalTokens}`);
    console.log(`Model: ${response.model}`);
    console.log(`Finish reason: ${response.choices[0].finishReason}`);
}

invokemixtral().catch(console.error);
```

### cURL: REST API Call

```bash
#!/bin/bash
# Direct REST API invocation

MISTRAL_API_KEY="your-api-key-here"
MODEL="open-mixtral-8x7b"
PROMPT="Explain quantum computing in simple terms."

curl -X POST "https://api.mistral.ai/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MISTRAL_API_KEY" \
  -d '{
    "model": "'"$MODEL"'",
    "messages": [
      {
        "role": "user",
        "content": "'"$PROMPT"'"
      }
    ],
    "temperature": 0.7,
    "max_tokens": 1000
  }' | jq '.'
```

---

## Spawning an Agent

### Python: Multi-Turn Agent

```python
#!/usr/bin/env python3
"""
Mixtral Agent - Multi-turn conversation handler
"""
import os
from mistralai import Mistral
from typing import List, Dict

class MixtralAgent:
    """
    An agent that maintains conversation context and invokes Mixtral
    """

    def __init__(self, api_key: str, model: str = "open-mixtral-8x7b",
                 system_prompt: str = None):
        """
        Initialize the agent

        Args:
            api_key: Mistral API key
            model: Model to use
            system_prompt: Optional system instructions
        """
        self.client = Mistral(api_key=api_key)
        self.model = model
        self.conversation_history: List[Dict[str, str]] = []

        # Add system prompt if provided
        if system_prompt:
            self.conversation_history.append({
                "role": "system",
                "content": system_prompt
            })

    def chat(self, user_message: str, temperature: float = 0.7,
             max_tokens: int = 1000) -> str:
        """
        Send a message and get a response

        Args:
            user_message: The user's message
            temperature: Randomness (0.0-1.0)
            max_tokens: Maximum tokens in response

        Returns:
            The assistant's response
        """
        # Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        # Invoke Mixtral
        response = self.client.chat.complete(
            model=self.model,
            messages=self.conversation_history,
            temperature=temperature,
            max_tokens=max_tokens
        )

        # Extract assistant's response
        assistant_message = response.choices[0].message.content

        # Add to conversation history
        self.conversation_history.append({
            "role": "assistant",
            "content": assistant_message
        })

        return assistant_message

    def get_history(self) -> List[Dict[str, str]]:
        """Get the full conversation history"""
        return self.conversation_history

    def clear_history(self, keep_system_prompt: bool = True):
        """Clear conversation history"""
        if keep_system_prompt and self.conversation_history and \
           self.conversation_history[0]["role"] == "system":
            self.conversation_history = [self.conversation_history[0]]
        else:
            self.conversation_history = []

    def export_conversation(self, filepath: str):
        """Export conversation to JSON file"""
        import json
        with open(filepath, 'w') as f:
            json.dump(self.conversation_history, f, indent=2)


# Usage Example
if __name__ == "__main__":
    # Initialize agent
    api_key = os.environ["MISTRAL_API_KEY"]
    agent = MixtralAgent(
        api_key=api_key,
        system_prompt="You are a helpful AI assistant specializing in physics."
    )

    # Multi-turn conversation
    response1 = agent.chat("What is quantum entanglement?")
    print(f"Assistant: {response1}\n")

    response2 = agent.chat("Can you give me a simple analogy?")
    print(f"Assistant: {response2}\n")

    response3 = agent.chat("How is this used in quantum computing?")
    print(f"Assistant: {response3}\n")

    # Export conversation
    agent.export_conversation("conversation.json")
    print("Conversation exported to conversation.json")
```

### Python: Async Agent (for high-throughput)

```python
#!/usr/bin/env python3
"""
Async Mixtral Agent - For parallel requests
"""
import os
import asyncio
from mistralai import Mistral
from typing import List, Dict

class AsyncMixtralAgent:
    """
    Asynchronous agent for parallel Mixtral invocations
    """

    def __init__(self, api_key: str, model: str = "open-mixtral-8x7b"):
        self.client = Mistral(api_key=api_key)
        self.model = model

    async def process_single(self, prompt: str, temperature: float = 0.7) -> Dict:
        """
        Process a single prompt asynchronously
        """
        response = await self.client.chat.complete_async(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature
        )

        return {
            "prompt": prompt,
            "response": response.choices[0].message.content,
            "tokens": response.usage.total_tokens
        }

    async def process_batch(self, prompts: List[str],
                          temperature: float = 0.7) -> List[Dict]:
        """
        Process multiple prompts in parallel
        """
        tasks = [self.process_single(p, temperature) for p in prompts]
        results = await asyncio.gather(*tasks)
        return results


# Usage Example
async def main():
    api_key = os.environ["MISTRAL_API_KEY"]
    agent = AsyncMixtralAgent(api_key=api_key)

    # Batch of prompts
    prompts = [
        "Explain relativity in one sentence.",
        "What is the speed of light?",
        "Define quantum mechanics.",
        "What is dark matter?"
    ]

    print("Processing batch of prompts in parallel...")
    results = await agent.process_batch(prompts)

    for i, result in enumerate(results, 1):
        print(f"\n--- Result {i} ---")
        print(f"Prompt: {result['prompt']}")
        print(f"Response: {result['response']}")
        print(f"Tokens: {result['tokens']}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Node.js: Agent Class

```javascript
#!/usr/bin/env node
/**
 * Mixtral Agent - Multi-turn conversation handler (Node.js)
 */
import Mistral from '@mistralai/mistralai';
import dotenv from 'dotenv';
import fs from 'fs/promises';

dotenv.config();

class MixtralAgent {
    constructor(apiKey, model = 'open-mixtral-8x7b', systemPrompt = null) {
        this.client = new Mistral({ apiKey });
        this.model = model;
        this.conversationHistory = [];

        if (systemPrompt) {
            this.conversationHistory.push({
                role: 'system',
                content: systemPrompt
            });
        }
    }

    async chat(userMessage, temperature = 0.7, maxTokens = 1000) {
        // Add user message
        this.conversationHistory.push({
            role: 'user',
            content: userMessage
        });

        // Invoke Mixtral
        const response = await this.client.chat.complete({
            model: this.model,
            messages: this.conversationHistory,
            temperature,
            maxTokens
        });

        // Extract response
        const assistantMessage = response.choices[0].message.content;

        // Add to history
        this.conversationHistory.push({
            role: 'assistant',
            content: assistantMessage
        });

        return assistantMessage;
    }

    getHistory() {
        return this.conversationHistory;
    }

    clearHistory(keepSystemPrompt = true) {
        if (keepSystemPrompt && this.conversationHistory.length > 0 &&
            this.conversationHistory[0].role === 'system') {
            this.conversationHistory = [this.conversationHistory[0]];
        } else {
            this.conversationHistory = [];
        }
    }

    async exportConversation(filepath) {
        await fs.writeFile(
            filepath,
            JSON.stringify(this.conversationHistory, null, 2)
        );
    }
}

// Usage Example
async function main() {
    const apiKey = process.env.MISTRAL_API_KEY;
    const agent = new MixtralAgent(
        apiKey,
        'open-mixtral-8x7b',
        'You are a helpful AI assistant specializing in physics.'
    );

    // Multi-turn conversation
    const response1 = await agent.chat('What is quantum entanglement?');
    console.log(`Assistant: ${response1}\n`);

    const response2 = await agent.chat('Can you give me a simple analogy?');
    console.log(`Assistant: ${response2}\n`);

    const response3 = await agent.chat('How is this used in quantum computing?');
    console.log(`Assistant: ${response3}\n`);

    // Export
    await agent.exportConversation('conversation.json');
    console.log('Conversation exported to conversation.json');
}

main().catch(console.error);
```

---

## Structured Responses

### Python: JSON Mode

```python
#!/usr/bin/env python3
"""
Get structured JSON responses from Mixtral
"""
import os
import json
from mistralai import Mistral

api_key = os.environ["MISTRAL_API_KEY"]
client = Mistral(api_key=api_key)

# Request structured output
response = client.chat.complete(
    model="open-mixtral-8x7b",
    messages=[
        {
            "role": "user",
            "content": """Extract the following information from this text and return as JSON:

            Text: "John Doe is a 35-year-old software engineer living in San Francisco.
            He works at TechCorp and earns $150,000 per year."

            Required fields:
            - name (string)
            - age (integer)
            - occupation (string)
            - location (string)
            - company (string)
            - salary (integer)

            Return ONLY valid JSON, no other text."""
        }
    ],
    response_format={"type": "json_object"}
)

# Parse JSON response
result = json.loads(response.choices[0].message.content)
print(json.dumps(result, indent=2))
```

### Python: Pydantic Models

```python
#!/usr/bin/env python3
"""
Use Pydantic models for strongly-typed responses
"""
import os
import json
from mistralai import Mistral
from pydantic import BaseModel, Field
from typing import List

class Person(BaseModel):
    """Structured person information"""
    name: str = Field(description="Full name")
    age: int = Field(description="Age in years")
    occupation: str = Field(description="Job title")
    location: str = Field(description="City of residence")
    company: str = Field(description="Employer name")
    salary: int = Field(description="Annual salary in USD")

class PeopleList(BaseModel):
    """List of people"""
    people: List[Person]

def extract_people(text: str) -> PeopleList:
    """
    Extract structured people data from text
    """
    api_key = os.environ["MISTRAL_API_KEY"]
    client = Mistral(api_key=api_key)

    # Generate JSON schema from Pydantic model
    schema = PeopleList.model_json_schema()

    # Create prompt with schema
    prompt = f"""Extract all people mentioned in the text below.

Text: {text}

Return the data as JSON matching this schema:
{json.dumps(schema, indent=2)}

Return ONLY valid JSON."""

    # Invoke Mixtral
    response = client.chat.complete(
        model="open-mixtral-8x7b",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )

    # Parse and validate with Pydantic
    result_json = json.loads(response.choices[0].message.content)
    validated_result = PeopleList(**result_json)

    return validated_result

# Usage
if __name__ == "__main__":
    text = """
    John Doe is a 35-year-old software engineer living in San Francisco.
    He works at TechCorp and earns $150,000 per year.

    Jane Smith, 28, is a data scientist at DataCo in New York City,
    making $120,000 annually.
    """

    result = extract_people(text)

    print("Extracted People:")
    for person in result.people:
        print(f"\n{person.name}:")
        print(f"  Age: {person.age}")
        print(f"  Job: {person.occupation} at {person.company}")
        print(f"  Location: {person.location}")
        print(f"  Salary: ${person.salary:,}")
```

### Python: Function Calling

```python
#!/usr/bin/env python3
"""
Mixtral with function calling for structured outputs
"""
import os
import json
from mistralai import Mistral

api_key = os.environ["MISTRAL_API_KEY"]
client = Mistral(api_key=api_key)

# Define available functions
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and country, e.g. Paris, France"
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "Temperature unit"
                    }
                },
                "required": ["location"]
            }
        }
    }
]

# Invoke with tools
response = client.chat.complete(
    model="open-mixtral-8x7b",
    messages=[
        {"role": "user", "content": "What's the weather like in Tokyo?"}
    ],
    tools=tools,
    tool_choice="auto"
)

# Check if function was called
if response.choices[0].message.tool_calls:
    tool_call = response.choices[0].message.tool_calls[0]
    function_name = tool_call.function.name
    function_args = json.loads(tool_call.function.arguments)

    print(f"Function called: {function_name}")
    print(f"Arguments: {json.dumps(function_args, indent=2)}")

    # Simulate function execution
    weather_result = {
        "location": function_args["location"],
        "temperature": 22,
        "unit": function_args.get("unit", "celsius"),
        "condition": "Partly cloudy"
    }

    # Send function result back to model
    final_response = client.chat.complete(
        model="open-mixtral-8x7b",
        messages=[
            {"role": "user", "content": "What's the weather like in Tokyo?"},
            response.choices[0].message,
            {
                "role": "tool",
                "name": function_name,
                "content": json.dumps(weather_result),
                "tool_call_id": tool_call.id
            }
        ],
        tools=tools
    )

    print(f"\nFinal response: {final_response.choices[0].message.content}")
```

---

## Advanced Features

### Error Handling & Retries

```python
#!/usr/bin/env python3
"""
Robust error handling and automatic retries
"""
import os
import time
from mistralai import Mistral
from mistralai.exceptions import (
    MistralException,
    MistralAPIException,
    MistralConnectionException
)

class RobustMixtralClient:
    """
    Mixtral client with automatic retries and error handling
    """

    def __init__(self, api_key: str, max_retries: int = 3):
        self.client = Mistral(api_key=api_key)
        self.max_retries = max_retries

    def invoke_with_retry(self, model: str, messages: list, **kwargs):
        """
        Invoke Mixtral with automatic retries on failure
        """
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.complete(
                    model=model,
                    messages=messages,
                    **kwargs
                )
                return response

            except MistralConnectionException as e:
                last_exception = e
                wait_time = 2 ** attempt  # Exponential backoff
                print(f"Connection error (attempt {attempt + 1}/{self.max_retries}). "
                      f"Retrying in {wait_time}s...")
                time.sleep(wait_time)

            except MistralAPIException as e:
                # Don't retry on client errors (4xx)
                if 400 <= e.status_code < 500:
                    raise
                # Retry on server errors (5xx)
                last_exception = e
                wait_time = 2 ** attempt
                print(f"API error {e.status_code} (attempt {attempt + 1}/{self.max_retries}). "
                      f"Retrying in {wait_time}s...")
                time.sleep(wait_time)

            except MistralException as e:
                # Unknown Mistral error
                print(f"Mistral error: {e}")
                raise

        # All retries exhausted
        raise last_exception

# Usage
if __name__ == "__main__":
    api_key = os.environ["MISTRAL_API_KEY"]
    client = RobustMixtralClient(api_key, max_retries=3)

    try:
        response = client.invoke_with_retry(
            model="open-mixtral-8x7b",
            messages=[{"role": "user", "content": "Hello!"}]
        )
        print(response.choices[0].message.content)
    except Exception as e:
        print(f"Failed after all retries: {e}")
```

### Rate Limiting & Token Management

```python
#!/usr/bin/env python3
"""
Token counting and rate limiting
"""
import os
import time
from mistralai import Mistral
from collections import deque
from datetime import datetime, timedelta

class RateLimitedMixtralClient:
    """
    Mixtral client with rate limiting
    """

    def __init__(self, api_key: str, requests_per_minute: int = 60):
        self.client = Mistral(api_key=api_key)
        self.requests_per_minute = requests_per_minute
        self.request_times = deque()

    def _wait_if_needed(self):
        """Wait if we've hit the rate limit"""
        now = datetime.now()

        # Remove requests older than 1 minute
        cutoff = now - timedelta(minutes=1)
        while self.request_times and self.request_times[0] < cutoff:
            self.request_times.popleft()

        # Check if we need to wait
        if len(self.request_times) >= self.requests_per_minute:
            sleep_time = (self.request_times[0] + timedelta(minutes=1) - now).total_seconds()
            if sleep_time > 0:
                print(f"Rate limit reached. Waiting {sleep_time:.1f}s...")
                time.sleep(sleep_time)

        # Record this request
        self.request_times.append(now)

    def count_tokens(self, text: str, model: str = "open-mixtral-8x7b") -> int:
        """
        Estimate token count (approximate)
        Mistral models use ~4 characters per token on average
        """
        # This is an approximation - use tiktoken for exact counts
        return len(text) // 4

    def chat(self, model: str, messages: list, **kwargs):
        """Rate-limited chat completion"""
        self._wait_if_needed()

        # Count input tokens
        total_chars = sum(len(m.get("content", "")) for m in messages)
        estimated_tokens = self.count_tokens(str(total_chars))
        print(f"Estimated input tokens: {estimated_tokens}")

        response = self.client.chat.complete(
            model=model,
            messages=messages,
            **kwargs
        )

        print(f"Actual tokens used: {response.usage.total_tokens}")
        return response

# Usage
if __name__ == "__main__":
    api_key = os.environ["MISTRAL_API_KEY"]
    client = RateLimitedMixtralClient(api_key, requests_per_minute=10)

    for i in range(15):
        print(f"\nRequest {i + 1}")
        response = client.chat(
            model="open-mixtral-8x7b",
            messages=[{"role": "user", "content": f"Count to {i + 1}"}]
        )
        print(response.choices[0].message.content[:100])
```

---

## Complete Examples

### Complete Production-Ready Script

```python
#!/usr/bin/env python3
"""
Production-ready Mixtral integration
Complete example with all features
"""
import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
from mistralai import Mistral
from mistralai.exceptions import MistralException
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('mixtral.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Pydantic models for structured output
class AnalysisResult(BaseModel):
    """Structured analysis result"""
    topic: str = Field(description="Main topic")
    sentiment: str = Field(description="Sentiment: positive, negative, or neutral")
    key_points: List[str] = Field(description="Key points extracted")
    confidence: float = Field(description="Confidence score 0-1")
    summary: str = Field(description="Brief summary")

class MixtralService:
    """
    Production-ready Mixtral service
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "open-mixtral-8x7b",
        output_dir: str = "./outputs"
    ):
        """
        Initialize the service

        Args:
            api_key: Mistral API key (defaults to env var)
            model: Model to use
            output_dir: Directory for output files
        """
        self.api_key = api_key or os.environ.get("MISTRAL_API_KEY")
        if not self.api_key:
            raise ValueError("MISTRAL_API_KEY not found in environment or arguments")

        self.client = Mistral(api_key=self.api_key)
        self.model = model
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        logger.info(f"Initialized MixtralService with model {model}")

    def invoke(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        save_output: bool = True
    ) -> Dict:
        """
        Invoke Mixtral with a prompt

        Args:
            prompt: User prompt
            system_prompt: Optional system instructions
            temperature: Randomness (0.0-1.0)
            max_tokens: Maximum response tokens
            save_output: Whether to save output to file

        Returns:
            Dictionary with response and metadata
        """
        logger.info(f"Invoking Mixtral with prompt: {prompt[:100]}...")

        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            # Call API
            response = self.client.chat.complete(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )

            # Extract result
            result = {
                "prompt": prompt,
                "response": response.choices[0].message.content,
                "model": response.model,
                "tokens": {
                    "prompt": response.usage.prompt_tokens,
                    "completion": response.usage.completion_tokens,
                    "total": response.usage.total_tokens
                },
                "finish_reason": response.choices[0].finish_reason,
                "timestamp": datetime.now().isoformat()
            }

            logger.info(f"Success. Tokens used: {result['tokens']['total']}")

            # Save to file if requested
            if save_output:
                self._save_result(result)

            return result

        except MistralException as e:
            logger.error(f"Mistral API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise

    def analyze_text(self, text: str) -> AnalysisResult:
        """
        Analyze text and return structured result

        Args:
            text: Text to analyze

        Returns:
            Structured analysis result
        """
        logger.info("Analyzing text...")

        # Get JSON schema
        schema = AnalysisResult.model_json_schema()

        # Build prompt
        prompt = f"""Analyze the following text and extract structured information.

Text: {text}

Return a JSON object matching this schema:
{json.dumps(schema, indent=2)}

Return ONLY valid JSON, no other text."""

        # Invoke with JSON mode
        response = self.client.chat.complete(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )

        # Parse and validate
        result_json = json.loads(response.choices[0].message.content)
        validated_result = AnalysisResult(**result_json)

        logger.info(f"Analysis complete. Sentiment: {validated_result.sentiment}")
        return validated_result

    def _save_result(self, result: Dict):
        """Save result to JSON file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = self.output_dir / f"result_{timestamp}.json"

        with open(filename, 'w') as f:
            json.dump(result, f, indent=2)

        logger.info(f"Saved result to {filename}")


def main():
    """Main entry point"""
    # Initialize service
    service = MixtralService(
        model="open-mixtral-8x7b",
        output_dir="./mixtral_outputs"
    )

    # Example 1: Simple invocation
    print("\n=== Example 1: Simple Invocation ===")
    result1 = service.invoke(
        prompt="Explain quantum computing in 3 sentences.",
        temperature=0.5
    )
    print(f"Response: {result1['response']}")
    print(f"Tokens: {result1['tokens']['total']}")

    # Example 2: With system prompt
    print("\n=== Example 2: With System Prompt ===")
    result2 = service.invoke(
        prompt="Write a haiku about AI.",
        system_prompt="You are a creative poet. Be concise and artistic.",
        temperature=0.9
    )
    print(f"Response: {result2['response']}")

    # Example 3: Structured analysis
    print("\n=== Example 3: Structured Analysis ===")
    text_to_analyze = """
    Artificial Intelligence is revolutionizing healthcare.
    AI systems can now detect diseases earlier and more accurately than ever before.
    However, concerns about data privacy and algorithmic bias remain significant challenges.
    Overall, the potential benefits appear to outweigh the risks if properly regulated.
    """
    analysis = service.analyze_text(text_to_analyze)
    print(f"Topic: {analysis.topic}")
    print(f"Sentiment: {analysis.sentiment}")
    print(f"Key Points:")
    for point in analysis.key_points:
        print(f"  - {point}")
    print(f"Summary: {analysis.summary}")
    print(f"Confidence: {analysis.confidence}")

    logger.info("All examples completed successfully")


if __name__ == "__main__":
    main()
```

### Environment Setup Script

```bash
#!/bin/bash
# setup-mixtral.sh
# Complete environment setup for Mixtral integration

set -e  # Exit on error

echo "=== Mixtral Integration Setup ==="

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed"
    exit 1
fi

echo "✓ Python 3 found: $(python3 --version)"

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "✓ Virtual environment created"

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install mistralai python-dotenv pydantic asyncio aiohttp

echo "✓ Dependencies installed"

# Check for API key
if [ -z "$MISTRAL_API_KEY" ]; then
    echo ""
    echo "MISTRAL_API_KEY not found in environment."
    echo "Please enter your Mistral API key:"
    read -r api_key

    # Save to .env
    echo "MISTRAL_API_KEY=$api_key" > .env
    echo "MISTRAL_MODEL=open-mixtral-8x7b" >> .env

    echo "✓ API key saved to .env"
else
    echo "✓ MISTRAL_API_KEY found in environment"
fi

# Create directory structure
mkdir -p outputs logs examples

echo "✓ Directories created"

# Test connection
echo ""
echo "Testing Mistral API connection..."
python3 << 'EOF'
import os
from dotenv import load_dotenv
load_dotenv()

from mistralai import Mistral

api_key = os.environ.get("MISTRAL_API_KEY")
client = Mistral(api_key=api_key)

try:
    response = client.chat.complete(
        model="open-mixtral-8x7b",
        messages=[{"role": "user", "content": "Hi"}]
    )
    print("✓ API connection successful!")
    print(f"Response: {response.choices[0].message.content}")
except Exception as e:
    print(f"✗ API connection failed: {e}")
    exit(1)
EOF

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To activate the environment, run:"
echo "  source venv/bin/activate"
echo ""
echo "To deactivate, run:"
echo "  deactivate"
```

---

## Quick Reference

### API Key Retrieval

```python
# From environment variable
import os
api_key = os.environ["MISTRAL_API_KEY"]

# From .env file
from dotenv import load_dotenv
load_dotenv()
api_key = os.environ["MISTRAL_API_KEY"]

# From file
with open(".mistral_key", "r") as f:
    api_key = f.read().strip()

# From macOS Keychain
import subprocess
result = subprocess.run(
    ["security", "find-generic-password", "-a", os.environ["USER"],
     "-s", "mistral-api-key", "-w"],
    capture_output=True,
    text=True
)
api_key = result.stdout.strip()
```

### Response Structure

```python
response = client.chat.complete(...)

# Access response text
text = response.choices[0].message.content

# Access metadata
model_used = response.model
finish_reason = response.choices[0].finish_reason  # "stop", "length", etc.

# Token usage
prompt_tokens = response.usage.prompt_tokens
completion_tokens = response.usage.completion_tokens
total_tokens = response.usage.total_tokens
```

### Common Parameters

```python
client.chat.complete(
    model="open-mixtral-8x7b",       # Model name
    messages=[...],                   # Conversation messages
    temperature=0.7,                  # 0.0-1.0 (lower = more deterministic)
    max_tokens=1000,                  # Maximum tokens in response
    top_p=1.0,                        # Nucleus sampling (0.0-1.0)
    random_seed=42,                   # For reproducible outputs
    safe_mode=False,                  # Enable content moderation
    response_format={"type": "json_object"}  # Force JSON output
)
```

---

## Resources

- **Mistral AI Console**: https://console.mistral.ai/
- **API Documentation**: https://docs.mistral.ai/
- **Python SDK**: https://github.com/mistralai/client-python
- **Pricing**: https://mistral.ai/technology/#pricing
- **Discord Community**: https://discord.gg/mistralai

---

**Last Updated**: February 2026
