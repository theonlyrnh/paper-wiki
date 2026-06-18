"""Knowledge graph construction from wiki pages."""

import re
import json
import logging
from pathlib import Path
from collections import defaultdict
from typing import Optional

import networkx as nx
from networkx.algorithms.community import louvain_communities

from backend.config import CONFIG

logger = logging.getLogger(__name__)

WIKI_BASE = Path(__file__).parent.parent.parent / CONFIG["storage"]["wiki_dir"]

SIGNALS = CONFIG.get("graph", {}).get("signals", {
    "direct_link": 3.0,
    "source_overlap": 4.0,
    "adamic_adar": 1.5,
    "type_affinity": 1.0,
})


class KnowledgeGraph:
    """Build and query the wiki knowledge graph."""

    def __init__(self):
        self.graph = nx.Graph()
        self._built = False

    def invalidate(self):
        """Mark cache as stale so next query triggers rebuild."""
        self._built = False

    def build(self, user_id: int = None):
        """Build the graph from wiki pages (optionally per-user)."""
        self.graph.clear()
        self._user_id = user_id
        pages = self._scan_pages(user_id)

        # Add nodes
        for name, meta in pages.items():
            self.graph.add_node(name, **meta)

        # Add edges: direct wikilinks
        for name, meta in pages.items():
            for link in meta.get("links", []):
                link_slug = self._slugify(link)
                if link_slug in pages and link_slug != name:
                    w = SIGNALS.get("direct_link", 3.0)
                    if self.graph.has_edge(name, link_slug):
                        self.graph[name][link_slug]["weight"] += w
                    else:
                        self.graph.add_edge(name, link_slug, weight=w, signal="direct_link")

        # Add edges: shared sources
        source_pages = defaultdict(list)
        for name, meta in pages.items():
            for src in meta.get("sources", []):
                source_pages[src].append(name)

        for src, page_list in source_pages.items():
            if len(page_list) > 1:
                w = SIGNALS.get("source_overlap", 4.0)
                for i in range(len(page_list)):
                    for j in range(i + 1, len(page_list)):
                        a, b = page_list[i], page_list[j]
                        if self.graph.has_edge(a, b):
                            self.graph[a][b]["weight"] += w
                            if "source_overlap" not in self.graph[a][b].get("signal", ""):
                                self.graph[a][b]["signal"] += "+source_overlap"
                        else:
                            self.graph.add_edge(a, b, weight=w, signal="source_overlap")

        # Compute Adamic-Adar scores for potential edges
        preds = nx.adamic_adar_index(self.graph, [
            (u, v) for u, v in nx.non_edges(self.graph)
            if self.graph.degree(u) > 0 and self.graph.degree(v) > 0
        ])
        aa_threshold = 0.5
        for u, v, score in preds:
            if score > aa_threshold:
                w = min(score * SIGNALS.get("adamic_adar", 1.5) / 5.0, 3.0)
                self.graph.add_edge(u, v, weight=w, signal="adamic_adar")

        # Add type affinity
        for u, v in self.graph.edges():
            if self.graph.nodes[u].get("type") == self.graph.nodes[v].get("type"):
                self.graph[u][v]["weight"] += SIGNALS.get("type_affinity", 1.0)

        # Compute communities
        if len(self.graph) > 3:
            try:
                communities = louvain_communities(self.graph, weight="weight", seed=42)
                for comm_id, comm in enumerate(communities):
                    for node in comm:
                        self.graph.nodes[node]["community"] = comm_id
            except Exception as e:
                logger.warning(f"Louvain community detection failed: {e}")

        self._built = True
        logger.info(f"Graph built: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges")

    def _scan_pages(self, user_id: int = None) -> dict:
        """Scan wiki pages and extract metadata (per-user)."""
        pages = {}
        wiki_dir = WIKI_BASE / str(user_id) if user_id else WIKI_BASE
        for subdir in ["sources", "entities", "concepts", ""]:
            search_dir = wiki_dir / subdir if subdir else wiki_dir
            if not search_dir.exists():
                continue
            for md_file in search_dir.glob("*.md"):
                if md_file.name in ("index.md", "log.md", "overview.md") and subdir:
                    continue
                page = self._parse_page(md_file, wiki_dir)
                if page:
                    pages[page["name"]] = page
        return pages

    def _parse_page(self, path: Path, wiki_dir: Path = None) -> Optional[dict]:
        """Parse a wiki page's frontmatter and extract links."""
        if wiki_dir is None:
            wiki_dir = WIKI_BASE
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return None

        try:
            rel = path.relative_to(wiki_dir)
        except ValueError:
            rel = Path(path.name)
        parts = rel.parts
        page_type = parts[0] if len(parts) > 1 else "root"

        # Parse YAML frontmatter (simple)
        fm = {}
        lines = content.split("\n")
        if lines and lines[0] == "---":
            for line in lines[1:]:
                if line == "---":
                    break
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if val.startswith("[") and val.endswith("]"):
                        try:
                            fm[key] = json.loads(val.replace("'", '"'))
                        except Exception:
                            fm[key] = val
                    else:
                        fm[key] = val.strip('"').strip("'")

        # Extract title
        title = fm.get("title", path.stem.replace("-", " ").title())

        # Extract wikilinks
        links = re.findall(r'\[\[([^\]]+)\]\]', content)

        # Extract sources
        sources = fm.get("sources", [])
        if isinstance(sources, str):
            sources = [sources]

        # Tags
        tags = fm.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]

        return {
            "name": path.stem,
            "title": title,
            "type": page_type,
            "links": links,
            "sources": sources,
            "tags": tags,
            "degree": 0,  # filled after graph construction
        }

    def _slugify(self, name: str) -> str:
        """Convert display name to filename slug."""
        slug = name.lower().strip()
        slug = re.sub(r'[^\w\u4e00-\u9fff\s-]', '', slug)
        slug = re.sub(r'[\s_]+', '-', slug)
        return slug

    def get_graph_data(self, user_id: int = None) -> dict:
        """Get graph data formatted for frontend visualization."""
        if not self._built or getattr(self, '_user_id', None) != user_id:
            self.build(user_id)

        nodes = []
        for name, data in self.graph.nodes(data=True):
            degree = self.graph.degree(name)
            # Weighted degree: only count strong signals for visual size
            import math
            strong_deg = sum(
                1 for _, _, d in self.graph.edges(name, data=True)
                if d.get('signal', '') in ('direct_link', 'source_overlap')
                   or 'source_overlap' in d.get('signal', '')
            )
            size = max(1.0, min(8.0, 1.0 + math.log(1 + strong_deg) * 2.0))
            nodes.append({
                "id": name,
                "label": data.get("title", name),
                "type": data.get("type", "unknown"),
                "community": data.get("community", 0),
                "degree": degree,
                "strong_degree": strong_deg,
                "size": round(size, 2),
            })

        edges = []
        for u, v, data in self.graph.edges(data=True):
            edges.append({
                "source": u,
                "target": v,
                "weight": round(data.get("weight", 1.0), 2),
                "signal": data.get("signal", "direct_link"),
            })

        # Community info
        communities = defaultdict(list)
        for name, data in self.graph.nodes(data=True):
            c = data.get("community", 0)
            communities[c].append(name)

        comm_info = {}
        for cid, members in communities.items():
            # Find most common type as label
            types = [self.graph.nodes[m].get("type", "?") for m in members]
            most_common_type = max(set(types), key=types.count) if types else "mixed"
            comm_info[str(cid)] = {
                "label": most_common_type,
                "members": len(members),
                "cohesion": round(self._community_cohesion(members), 2),
            }

        return {
            "nodes": nodes,
            "edges": edges,
            "communities": comm_info,
        }

    def _community_cohesion(self, members: list) -> float:
        """Compute internal edge density of a community."""
        if len(members) < 2:
            return 1.0
        sub = self.graph.subgraph(members)
        max_edges = len(members) * (len(members) - 1) / 2
        actual_edges = sub.number_of_edges()
        return actual_edges / max_edges if max_edges > 0 else 0.0

    def get_node_neighbors(self, node_id: str, user_id: int = None) -> dict:
        """Get a node's details and its neighbors."""
        if not self._built or getattr(self, '_user_id', None) != user_id:
            self.build(user_id)

        if node_id not in self.graph:
            return {"error": "Node not found"}

        data = dict(self.graph.nodes[node_id])
        neighbors = []
        for neighbor in self.graph.neighbors(node_id):
            edge = self.graph[node_id][neighbor]
            neighbors.append({
                "id": neighbor,
                "label": self.graph.nodes[neighbor].get("title", neighbor),
                "weight": edge.get("weight", 1.0),
                "signal": edge.get("signal", ""),
            })

        neighbors.sort(key=lambda x: -x["weight"])
        return {
            "node": {"id": node_id, **data},
            "neighbors": neighbors[:20],
        }

    def get_insights(self, user_id: int = None) -> dict:
        """Generate graph insights: surprising connections, knowledge gaps."""
        if not self._built or getattr(self, '_user_id', None) != user_id:
            self.build(user_id)

        insights = {
            "surprising_connections": [],
            "knowledge_gaps": [],
            "hubs": [],
            "isolated": [],
        }

        # Hubs: high degree nodes
        if self.graph.number_of_nodes() > 0:
            degree_sorted = sorted(self.graph.degree, key=lambda x: -x[1])
            insights["hubs"] = [
                {
                    "id": name,
                    "label": self.graph.nodes[name].get("title", name),
                    "degree": deg,
                }
                for name, deg in degree_sorted[:10] if deg > 0
            ]

        # Isolated nodes
        for name, deg in self.graph.degree:
            if deg == 0:
                insights["isolated"].append({
                    "id": name,
                    "label": self.graph.nodes[name].get("title", name),
                })

        # Surprising connections: edges between different communities
        for u, v, data in self.graph.edges(data=True):
            cu = self.graph.nodes[u].get("community", 0)
            cv = self.graph.nodes[v].get("community", 0)
            if cu != cv:
                insights["surprising_connections"].append({
                    "source_id": u,
                    "source": self.graph.nodes[u].get("title", u),
                    "target_id": v,
                    "target": self.graph.nodes[v].get("title", v),
                    "source_community": cu,
                    "target_community": cv,
                    "weight": data.get("weight", 1.0),
                })

        insights["surprising_connections"].sort(key=lambda x: -x["weight"])
        insights["surprising_connections"] = insights["surprising_connections"][:10]

        # Knowledge gaps: concepts mentioned in wikilinks but without their own page
        all_links = set()
        for name, data in self.graph.nodes(data=True):
            all_links.update(data.get("links", []))
        existing = set(self.graph.nodes())
        for link in all_links:
            slug = self._slugify(link)
            if slug not in existing:
                insights["knowledge_gaps"].append({
                    "name": link,
                    "referenced_by": sum(
                        1 for n, d in self.graph.nodes(data=True)
                        if link in d.get("links", [])
                    ),
                })

        insights["knowledge_gaps"].sort(key=lambda x: -x["referenced_by"])
        insights["knowledge_gaps"] = insights["knowledge_gaps"][:10]

        return insights
