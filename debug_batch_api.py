#!/usr/bin/env python3
"""Diagnostic script to test Mistral Batch API and understand the hanging issue."""

import asyncio
import json
import os
from io import BytesIO

from mistralai import File, Mistral


async def test_batch_api():
    """Test the Mistral Batch API with a simple example."""

    # Load API key
    import keyring
    api_key = keyring.get_password("objlib-mistral", "api_key")
    if not api_key:
        print("ERROR: No API key found in keyring")
        return

    print("✓ API key loaded")

    # Initialize client
    client = Mistral(api_key=api_key)
    print("✓ Mistral client initialized")

    # Step 1: Create JSONL file with test requests
    print("\n=== Step 1: Creating JSONL file ===")
    buffer = BytesIO()

    test_requests = [
        {
            "custom_id": "test-0",
            "body": {
                "model": "mistral-small-latest",
                "messages": [{"role": "user", "content": "What is 2+2?"}],
                "max_tokens": 100,
            }
        },
        {
            "custom_id": "test-1",
            "body": {
                "model": "mistral-small-latest",
                "messages": [{"role": "user", "content": "What is the capital of France?"}],
                "max_tokens": 100,
            }
        },
    ]

    for request in test_requests:
        buffer.write(json.dumps(request).encode("utf-8"))
        buffer.write(b"\n")

    print(f"✓ Created JSONL with {len(test_requests)} requests")
    print(f"  Sample: {test_requests[0]}")

    # Step 2: Upload file
    print("\n=== Step 2: Uploading file ===")
    try:
        uploaded_file = client.files.upload(
            file=File(file_name="test-batch.jsonl", content=buffer.getvalue()),
            purpose="batch"
        )
        print(f"✓ File uploaded: {uploaded_file.id}")
        print(f"  Filename: {uploaded_file.filename}")
        print(f"  Purpose: {uploaded_file.purpose}")
    except Exception as e:
        print(f"✗ File upload failed: {e}")
        return

    # Step 3: Create batch job
    print("\n=== Step 3: Creating batch job ===")
    try:
        batch_job = client.batch.jobs.create(
            input_files=[uploaded_file.id],
            model="mistral-small-latest",
            endpoint="/v1/chat/completions",
            metadata={"test": "diagnostic"}
        )
        print(f"✓ Batch job created: {batch_job.id}")
        print(f"  Status: {batch_job.status}")
        print(f"  Total requests: {batch_job.total_requests}")
    except Exception as e:
        print(f"✗ Batch job creation failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # Step 4: Poll for completion
    print("\n=== Step 4: Polling for completion ===")
    import time
    max_polls = 60
    poll_count = 0

    while batch_job.status in ["QUEUED", "RUNNING"] and poll_count < max_polls:
        poll_count += 1
        time.sleep(2)
        batch_job = client.batch.jobs.get(job_id=batch_job.id)
        print(f"  Poll {poll_count}: Status={batch_job.status}, "
              f"Succeeded={batch_job.succeeded_requests}/{batch_job.total_requests}")

    if batch_job.status == "SUCCESS":
        print(f"✓ Batch completed successfully")
    else:
        print(f"✗ Batch ended with status: {batch_job.status}")

    # Step 5: Download results
    if batch_job.output_file:
        print(f"\n=== Step 5: Downloading results ===")
        try:
            output_file = client.files.download(file_id=batch_job.output_file)
            output_content = b""
            for chunk in output_file.stream:
                output_content += chunk

            output_text = output_content.decode("utf-8")
            print(f"✓ Downloaded {len(output_content)} bytes")
            print(f"\n=== Output (first 500 chars) ===")
            print(output_text[:500])

            # Parse JSONL
            results = []
            for line in output_text.strip().split("\n"):
                if line:
                    results.append(json.loads(line))

            print(f"\n=== Parsed {len(results)} results ===")
            for result in results:
                print(f"  Custom ID: {result.get('custom_id')}")
                if 'response' in result:
                    content = result['response']['body']['choices'][0]['message']['content']
                    print(f"    Response: {content[:100]}...")
                if 'error' in result:
                    print(f"    Error: {result['error']}")

        except Exception as e:
            print(f"✗ Download failed: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("✗ No output file available")

    print("\n=== Test complete ===")


if __name__ == "__main__":
    asyncio.run(test_batch_api())
