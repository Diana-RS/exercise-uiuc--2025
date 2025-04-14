#!/usr/bin/env python3
"""
Test Assertion Extractor
"""

import ast
import csv
import logging
from pathlib import Path
import argparse
from typing import Dict, List, Tuple, Set, Optional
import os
import shutil
import subprocess
import asyncio
from collections import defaultdict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_TEMP_DIR = Path("/tmp/test_extractor")


class AssertionExtractor(ast.NodeVisitor):
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.current_file: Optional[str] = None
        self.current_class: Optional[str] = None
        self.current_func: Optional[str] = None
        self.assertions: Set[Tuple] = set()
        self.class_hierarchy: Dict[str, List[str]] = {}
        self.class_definitions: Dict[str, Tuple[str, ast.ClassDef]] = {}
        self.function_defs: Dict[Tuple, ast.FunctionDef] = {}
        self.call_graph: Dict[Tuple, Set[Tuple]] = defaultdict(set)
        self.function_assertions: Dict[Tuple, Set[Tuple]] = defaultdict(set)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_hierarchy[node.name] = [
            base.id for base in node.bases if isinstance(base, ast.Name)
        ]
        self.class_definitions[node.name] = (self.current_file, node)

        old_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = old_class

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        old_func = self.current_func
        self.current_func = node.name
        func_key = self._current_func_key()

        self.function_defs[func_key] = node
        self._process_function_body(node.body)
        self.generic_visit(node)

        self.current_func = old_func

    def _process_function_body(self, body: List[ast.stmt]) -> None:
        for stmt in body:
            for node in ast.walk(stmt):
                self._process_node(node)

    def _process_node(self, node: ast.AST) -> None:
        if isinstance(node, ast.Assert):
            self._record_assertion(node)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr.lower().startswith("assert"):
                    self._record_assertion(node)
                elif (
                    node.func.attr in ["called", "called_once", "called_with"]
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "assert"
                ):
                    self._record_assertion(node)
            elif isinstance(node.func, ast.Name):
                if node.func.id.lower().startswith("assert"):
                    self._record_assertion(node)
            elif (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute)
            ):
                if node.func.value.attr == "testing" and node.func.attr.lower().startswith("assert"):
                    self._record_assertion(node)

            self._record_function_call(node)

    def _record_assertion(self, node: ast.AST) -> None:
        assertion = (
            self.current_file,
            self.current_class or "",
            self.current_func or "",
            node.lineno,
            ast.unparse(node).strip()
        )
        self.assertions.add(assertion)
        self.function_assertions[self._current_func_key()].add(assertion)

    def _record_function_call(self, node: ast.Call) -> None:
        caller = self._current_func_key()
        if isinstance(node.func, ast.Name):
            self.call_graph[caller].add((self.current_file, self.current_class, node.func.id))
        elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            self.call_graph[caller].add((self.current_file, node.func.value.id, node.func.attr))

    def _current_func_key(self) -> Tuple:
        return (self.current_file, self.current_class, self.current_func)

    def resolve_transitive_assertions(self) -> None:
        visited = set()

        def resolve(func_key: Tuple) -> Set[Tuple]:
            if func_key in visited:
                return set()
            visited.add(func_key)

            assertions = set(self.function_assertions.get(func_key, set()))
            for callee in self.call_graph.get(func_key, set()):
                assertions.update(resolve(callee))

            return assertions

        for func_key in self.function_defs:
            if func_key not in visited:
                self.assertions.update(resolve(func_key))

    def resolve_inherited_methods(self) -> None:
        for class_name, (file, class_node) in self.class_definitions.items():
            bases = self.class_hierarchy.get(class_name, [])
            for base in bases:
                if base in self.class_definitions:
                    _, base_node = self.class_definitions[base]
                    for item in base_node.body:
                        if isinstance(item, ast.FunctionDef):
                            func_key = (file, base, item.name)
                            if func_key not in self.function_defs:
                                self.function_defs[func_key] = item
                                self.current_file = file
                                self.current_class = base
                                self.current_func = item.name
                                self._process_function_body(item.body)

    def finalize(self):
        self.resolve_inherited_methods()
        self.resolve_transitive_assertions()


async def clone_repo(repo_url: str, dest_folder: Path) -> None:
    if dest_folder.exists():
        shutil.rmtree(dest_folder, ignore_errors=True)

    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth=1", repo_url, str(dest_folder),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Failed to clone repository: {stderr.decode()}")


def find_test_files(base_path: Path) -> List[Path]:
    test_files = []
    for pattern in ["*test*.py", "test_*.py", "*_test.py", "tests.py", "*/tests/*.py", "*/test/*.py"]:
        test_files.extend(base_path.rglob(pattern))
    return [f for f in test_files if "__pycache__" not in f.parts]


async def process_file(file_path: Path, extractor: AssertionExtractor) -> None:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
        extractor.current_file = str(file_path.relative_to(extractor.repo_root))
        extractor.visit(tree)
    except (SyntaxError, UnicodeDecodeError) as e:
        logger.warning(f"Could not parse {file_path}: {str(e)}")


async def process_repository(repo_url: str, output_csv: Path) -> None:
    repo_name = repo_url.split("/")[-1].replace(".git", "")
    temp_dir = DEFAULT_TEMP_DIR / repo_name

    try:
        await clone_repo(repo_url, temp_dir)
        extractor = AssertionExtractor(temp_dir)

        test_files = find_test_files(temp_dir)
        await asyncio.gather(*[
            process_file(file, extractor) for file in test_files
        ])

        extractor.finalize()

        logger.info(f"Extracted {len(extractor.assertions)} assertions.")

        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["filepath", "testclass", "testname", "line number", "assert string"])
            writer.writerows(sorted(extractor.assertions))

    except Exception as e:
        logger.error(f"Error processing repository: {str(e)}")
        raise
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Extract test assertions from Python repositories.")
    parser.add_argument("repo_url", help="GitHub repository URL")
    parser.add_argument("output_csv", help="Output CSV path")
    args = parser.parse_args()

    try:
        asyncio.run(process_repository(args.repo_url, Path(args.output_csv)))
        logger.info(f"Successfully extracted assertions to {args.output_csv}")
    except Exception as e:
        logger.error(f"Extraction failed: {str(e)}")
        exit(1)


if __name__ == "__main__":
    main()