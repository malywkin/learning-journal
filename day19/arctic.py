"""Arctic Shift Reddit archive client — standard library only."""

import json
import urllib.parse
import urllib.request
from typing import Optional

BASE = "https://arctic-shift.photon-reddit.com"
_HEADERS = {"User-Agent": "life-os-reddit-mcp/1.0"}
_TIMEOUT = 25


def _get(path: str, params: dict) -> dict:
    """Make a GET request and return parsed JSON. Raise on error envelope or HTTP error."""
    # Remove None values
    clean = {k: str(v) for k, v in params.items() if v is not None}
    url = BASE + path
    if clean:
        url = url + "?" + urllib.parse.urlencode(clean)
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        body = resp.read()
    data = json.loads(body)
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(data["error"])
    return data


def _strip_prefix(s: str, prefix: str) -> str:
    if s and s.startswith(prefix):
        return s[len(prefix):]
    return s


def search_posts(
    subreddit=None,
    query=None,
    author=None,
    sort="desc",
    limit=25,
    after=None,
    before=None,
) -> list[dict]:
    """Search posts via /api/posts/search. Returns the data list."""
    params = {
        "subreddit": subreddit,
        "query": query,
        "author": author,
        "sort": sort,
        "limit": limit,
        "after": after,
        "before": before,
    }
    result = _get("/api/posts/search", params)
    return result.get("data", [])


def search_comments(
    subreddit=None,
    author=None,
    link_id=None,
    body=None,
    sort="desc",
    limit=25,
) -> list[dict]:
    """Search comments via /api/comments/search. Returns the data list."""
    if link_id:
        link_id = _strip_prefix(link_id, "t3_")
    params = {
        "subreddit": subreddit,
        "author": author,
        "link_id": link_id,
        "body": body,
        "sort": sort,
        "limit": limit,
    }
    result = _get("/api/comments/search", params)
    return result.get("data", [])


def _flatten_tree(nodes: list, out: list, limit: int) -> None:
    """Depth-first flatten of comment tree nodes. Skips 'more' nodes and non-dict items."""
    for node in nodes:
        if len(out) >= limit:
            return
        # Skip non-dict items (bare strings, etc.)
        if not isinstance(node, dict):
            continue
        kind = node.get("kind")
        if kind == "more":
            continue
        node_data = node.get("data", {})
        if not isinstance(node_data, dict):
            continue
        out.append(node_data)
        # Recurse into replies
        replies = node_data.get("replies")
        if replies and isinstance(replies, dict):
            child_nodes = replies.get("data", [])
            if child_nodes and isinstance(child_nodes, list):
                _flatten_tree(child_nodes, out, limit)


def get_post_comments(post_id: str, limit: int = 200) -> list[dict]:
    """Fetch and flatten comment tree for a post. Returns flat list of comment dicts."""
    post_id = _strip_prefix(post_id, "t3_")
    params = {
        "link_id": post_id,
        "limit": min(limit, 9999),
    }
    result = _get("/api/comments/tree", params)
    nodes = result.get("data", [])
    out: list[dict] = []
    _flatten_tree(nodes, out, limit)
    return out


def get_posts_by_ids(ids: list[str]) -> list[dict]:
    """Fetch posts by IDs via /api/posts/ids. Returns data list."""
    clean_ids = [_strip_prefix(i, "t3_") for i in ids]
    params = {"ids": ",".join(clean_ids)}
    result = _get("/api/posts/ids", params)
    return result.get("data", [])


def find_subreddit(name_or_prefix: str, limit: int = 10) -> list[dict]:
    """Find subreddits by prefix via /api/subreddits/search. Returns data list."""
    name_or_prefix = _strip_prefix(name_or_prefix, "r/")
    params = {
        "subreddit_prefix": name_or_prefix,
        "limit": limit,
    }
    result = _get("/api/subreddits/search", params)
    return result.get("data", [])
