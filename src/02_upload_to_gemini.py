#!/usr/bin/env python3
"""
Gemini Upload - Phase 2: Upload files to Gemini File API with metadata

This script uploads the scanned library files to Gemini and creates a searchable corpus.

Usage:
    python 02_upload_to_gemini.py --catalog ../data/library_catalog.json
    python 02_upload_to_gemini.py --batch-size 50 --resume
"""

import os
import json
import time
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

try:
    import google.generativeai as genai
except ImportError:
    print("Error: google-generativeai package not installed")
    print("Install with: pip install google-generativeai")
    exit(1)

try:
    from tqdm import tqdm
except ImportError:
    print("Warning: tqdm not installed. Install for progress bars: pip install tqdm")
    tqdm = None


class GeminiUploader:
    """Uploads library files to Gemini File API with rich metadata"""

    def __init__(self, api_key: Optional[str] = None, corpus_name: str = "objectivism-library-v1"):
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found. Set environment variable or pass as argument.")

        genai.configure(api_key=self.api_key)
        self.corpus_name = corpus_name
        self.corpus = None
        self.uploaded_files = []
        self.failed_uploads = []
        self.state_file = Path(f"../data/upload_state_{corpus_name}.json")

    def create_or_get_corpus(self) -> Any:
        """Create corpus or get existing one"""
        print(f"Setting up corpus: {self.corpus_name}")

        try:
            # Try to get existing corpus
            corpora = genai.list_corpora()
            for corpus in corpora:
                if corpus.name.endswith(self.corpus_name):
                    print(f"Found existing corpus: {corpus.name}")
                    self.corpus = corpus
                    return corpus

            # Create new corpus
            print("Creating new corpus...")
            self.corpus = genai.create_corpus(
                name=self.corpus_name,
                display_name=f"Objectivism Library - {datetime.now().strftime('%Y-%m-%d')}"
            )
            print(f"Created corpus: {self.corpus.name}")
            return self.corpus

        except Exception as e:
            print(f"Error with corpus: {e}")
            print("\nNote: Gemini File API may require specific setup.")
            print("See: https://ai.google.dev/gemini-api/docs/file-search")
            raise

    def load_state(self) -> Dict[str, Any]:
        """Load upload state for resume capability"""
        if self.state_file.exists():
            with open(self.state_file, 'r') as f:
                return json.load(f)
        return {'uploaded': [], 'failed': [], 'last_index': 0}

    def save_state(self, state: Dict[str, Any]):
        """Save upload state"""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)

    def prepare_metadata_for_gemini(self, metadata: Dict[str, Any]) -> List[Dict[str, str]]:
        """Convert our metadata schema to Gemini custom_metadata format"""
        gemini_metadata = []

        def flatten_dict(d: Dict, prefix: str = ""):
            """Flatten nested dict for Gemini metadata"""
            for key, value in d.items():
                new_key = f"{prefix}.{key}" if prefix else key

                if isinstance(value, dict):
                    flatten_dict(value, new_key)
                elif isinstance(value, (list, tuple)):
                    # Store list as comma-separated string
                    gemini_metadata.append({
                        "key": new_key,
                        "string_value": ", ".join(str(v) for v in value)
                    })
                elif value is not None:
                    gemini_metadata.append({
                        "key": new_key,
                        "string_value": str(value)
                    })

        # Flatten all metadata sections
        flatten_dict(metadata)

        return gemini_metadata

    def upload_file(self, file_metadata: Dict[str, Any], library_root: str) -> Optional[Any]:
        """Upload single file to Gemini"""
        file_path = Path(library_root) / file_metadata['core']['source_path']

        if not file_path.exists():
            print(f"Warning: File not found: {file_path}")
            return None

        try:
            # Upload file
            uploaded_file = genai.upload_file(
                path=str(file_path),
                display_name=file_metadata['intellectual']['title'][:100]  # Limit length
            )

            # Wait for processing
            max_wait = 60  # seconds
            waited = 0
            while uploaded_file.state.name == "PROCESSING" and waited < max_wait:
                time.sleep(2)
                waited += 2
                uploaded_file = genai.get_file(uploaded_file.name)

            if uploaded_file.state.name == "FAILED":
                raise Exception(f"File processing failed: {uploaded_file.state.name}")

            return uploaded_file

        except Exception as e:
            print(f"Error uploading {file_path}: {e}")
            return None

    def create_document_in_corpus(self, uploaded_file: Any, file_metadata: Dict[str, Any]) -> bool:
        """Create document in corpus with metadata"""
        try:
            # Prepare metadata
            custom_metadata = self.prepare_metadata_for_gemini(file_metadata)

            # Create document
            document = self.corpus.create_document(
                name=f"doc-{uploaded_file.name.split('/')[-1]}",
                display_name=file_metadata['intellectual']['title'],
                custom_metadata=custom_metadata
            )

            # Create chunk linking to file
            document.create_chunk(
                data={"string_value": uploaded_file.uri}
            )

            return True

        except Exception as e:
            print(f"Error creating document: {e}")
            return False

    def upload_batch(self, catalog: Dict[str, Any], library_root: str,
                    batch_size: int = 100, resume: bool = False) -> Dict[str, Any]:
        """Upload files in batches"""

        files = catalog['files']
        total = len(files)

        # Load state if resuming
        state = self.load_state() if resume else {'uploaded': [], 'failed': [], 'last_index': 0}
        start_index = state['last_index']

        print(f"\nUploading {total} files to Gemini...")
        if resume and start_index > 0:
            print(f"Resuming from index {start_index}")

        # Setup progress tracking
        iterator = range(start_index, total)
        if tqdm:
            iterator = tqdm(iterator, initial=start_index, total=total, desc="Uploading")

        for i in iterator:
            file_metadata = files[i]

            try:
                # Upload file
                uploaded_file = self.upload_file(file_metadata, library_root)
                if not uploaded_file:
                    self.failed_uploads.append({
                        'index': i,
                        'path': file_metadata['core']['source_path'],
                        'error': 'Upload failed'
                    })
                    continue

                # Create document with metadata
                success = self.create_document_in_corpus(uploaded_file, file_metadata)
                if success:
                    self.uploaded_files.append({
                        'index': i,
                        'file_id': uploaded_file.name,
                        'path': file_metadata['core']['source_path']
                    })
                else:
                    self.failed_uploads.append({
                        'index': i,
                        'path': file_metadata['core']['source_path'],
                        'error': 'Document creation failed'
                    })

            except Exception as e:
                print(f"\nError at index {i}: {e}")
                self.failed_uploads.append({
                    'index': i,
                    'path': file_metadata['core']['source_path'],
                    'error': str(e)
                })

            # Save state every batch_size files
            if (i + 1) % batch_size == 0:
                state = {
                    'uploaded': [u['path'] for u in self.uploaded_files],
                    'failed': self.failed_uploads,
                    'last_index': i + 1,
                    'timestamp': datetime.now().isoformat()
                }
                self.save_state(state)

                if not tqdm:
                    print(f"Progress: {i+1}/{total} ({100*(i+1)/total:.1f}%)")

            # Rate limiting - be nice to the API
            time.sleep(0.5)

        # Final state save
        state = {
            'uploaded': [u['path'] for u in self.uploaded_files],
            'failed': self.failed_uploads,
            'last_index': total,
            'completed': True,
            'timestamp': datetime.now().isoformat()
        }
        self.save_state(state)

        return state

    def print_summary(self, state: Dict[str, Any]):
        """Print upload summary"""
        print("\n" + "="*60)
        print("UPLOAD SUMMARY")
        print("="*60)
        print(f"Total files processed: {state['last_index']}")
        print(f"Successfully uploaded: {len(state['uploaded'])}")
        print(f"Failed uploads: {len(state['failed'])}")

        if state['failed']:
            print("\nFailed uploads:")
            for failure in state['failed'][:10]:  # Show first 10
                print(f"  - {failure['path']}")
                print(f"    Error: {failure['error']}")
            if len(state['failed']) > 10:
                print(f"  ... and {len(state['failed']) - 10} more")

        print(f"\nCorpus name: {self.corpus_name}")
        print(f"State saved to: {self.state_file}")
        print()

    def verify_upload(self) -> bool:
        """Verify upload by running test query"""
        print("\nVerifying upload with test query...")
        try:
            # Simple test query
            results = self.corpus.query(
                query="What is Objectivism?",
                results_count=5
            )

            if results:
                print("✓ Corpus is searchable!")
                print(f"  Test query returned {len(results)} results")
                return True
            else:
                print("✗ No results returned from test query")
                return False

        except Exception as e:
            print(f"✗ Verification failed: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description='Upload library to Gemini File API')
    parser.add_argument('--catalog', type=str,
                       default='../data/library_catalog.json',
                       help='Path to catalog JSON from scan phase')
    parser.add_argument('--library-root', type=str,
                       default='/Volumes/U32 Shadow/Objectivism Library',
                       help='Path to library root folder')
    parser.add_argument('--corpus-name', type=str,
                       default='objectivism-library-v1',
                       help='Name for the Gemini corpus')
    parser.add_argument('--batch-size', type=int, default=100,
                       help='Save state every N files')
    parser.add_argument('--resume', action='store_true',
                       help='Resume from last saved state')
    parser.add_argument('--api-key', type=str,
                       help='Gemini API key (or use GEMINI_API_KEY env var)')

    args = parser.parse_args()

    # Load catalog
    print(f"Loading catalog: {args.catalog}")
    with open(args.catalog, 'r') as f:
        catalog = json.load(f)

    print(f"Catalog contains {len(catalog['files'])} files")

    # Create uploader
    uploader = GeminiUploader(api_key=args.api_key, corpus_name=args.corpus_name)

    # Create/get corpus
    uploader.create_or_get_corpus()

    # Upload
    print(f"\nStarting upload (batch size: {args.batch_size})...")
    state = uploader.upload_batch(
        catalog=catalog,
        library_root=args.library_root,
        batch_size=args.batch_size,
        resume=args.resume
    )

    # Print summary
    uploader.print_summary(state)

    # Verify
    if state.get('completed'):
        uploader.verify_upload()

    print("\nDone! Next step: python 03_query_interface.py")


if __name__ == '__main__':
    main()
