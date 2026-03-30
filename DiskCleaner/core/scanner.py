import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .utils import file_stat_safe


@dataclass
class Node:
    path: str
    size: int = 0
    files: int = 0
    children: Dict[str, "Node"] = field(default_factory=dict)


class DiskScanner:
    def __init__(self):
        self.cancel_requested = False

    def cancel(self) -> None:
        self.cancel_requested = True

    def scan_tree(self, root: str, progress_cb=None) -> Optional[Node]:
        self.cancel_requested = False
        root_node = Node(path=root)
        stack: List[Node] = [root_node]

        while stack and not self.cancel_requested:
            node = stack.pop()
            try:
                with os.scandir(node.path) as it:
                    for entry in it:
                        if self.cancel_requested:
                            return None
                        if progress_cb:
                            progress_cb(entry.path)
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                child = Node(path=entry.path)
                                node.children[entry.name] = child
                                stack.append(child)
                            elif entry.is_file(follow_symlinks=False):
                                st = file_stat_safe(entry.path)
                                if st:
                                    node.size += st.st_size
                                    node.files += 1
                        except (PermissionError, FileNotFoundError, OSError):
                            continue
            except (PermissionError, FileNotFoundError, OSError):
                continue

        self._rollup_sizes(root_node)
        return root_node

    def _rollup_sizes(self, node: Node) -> None:
        for child in node.children.values():
            self._rollup_sizes(child)
            node.size += child.size
            node.files += child.files

    @staticmethod
    def top_children(node: Node, limit: int = 200):
        return sorted(node.children.values(), key=lambda n: n.size, reverse=True)[:limit]
