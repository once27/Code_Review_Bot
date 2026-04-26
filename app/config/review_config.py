"""
Review Configuration — .codereview.yml parser.

Allows per-repo customization of the review bot behavior. The config
file is fetched from the repo root and parsed into a ReviewConfig
dataclass. Falls back to sensible defaults if no config file exists.

Example .codereview.yml:
    enabled_agents:
      - security
      - logic

    ignore:
      - "*.md"
      - "docs/**"
      - "tests/fixtures/**"

    threshold: warning
    max_comments: 15

    custom_rules:
      - "All database queries must use parameterized statements"
      - "Never use print() for logging; use the logging module"
"""

import logging
import fnmatch
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger("app.config.review_config")

# All available agent types
ALL_AGENTS = frozenset({"security", "performance", "logic", "style"})

# Valid thresholds
VALID_THRESHOLDS = frozenset({"critical", "warning", "suggestion"})


@dataclass
class ReviewConfig:
    """Per-repo review configuration parsed from .codereview.yml."""

    # Which agents to run (default: all)
    enabled_agents: list[str] = field(default_factory=lambda: list(ALL_AGENTS))

    # Glob patterns for files to ignore
    ignore: list[str] = field(default_factory=list)

    # Minimum severity to post (default: suggestion = show all)
    threshold: str = "suggestion"

    # Max comments per PR
    max_comments: int = 20

    # Custom rules injected into agent prompts
    custom_rules: list[str] = field(default_factory=list)

    def should_review_file(self, filepath: str) -> bool:
        """Check if a file should be reviewed based on ignore patterns."""
        for pattern in self.ignore:
            if fnmatch.fnmatch(filepath, pattern):
                return False
            # Also check basename for simple patterns like "*.md"
            basename = filepath.rsplit("/", 1)[-1] if "/" in filepath else filepath
            if fnmatch.fnmatch(basename, pattern):
                return False
        return True


def parse_review_config(yaml_content: str | None) -> ReviewConfig:
    """
    Parse .codereview.yml content into a ReviewConfig.

    Args:
        yaml_content: Raw YAML string. None or empty = defaults.

    Returns:
        ReviewConfig with validated values, falling back to defaults
        for any missing or invalid fields.
    """
    if not yaml_content:
        logger.info("No .codereview.yml found — using defaults")
        return ReviewConfig()

    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as exc:
        logger.warning("Invalid YAML in .codereview.yml: %s — using defaults", exc)
        return ReviewConfig()

    if not isinstance(data, dict):
        logger.warning(".codereview.yml is not a mapping — using defaults")
        return ReviewConfig()

    config = ReviewConfig()

    # enabled_agents
    if "enabled_agents" in data:
        raw_agents = data["enabled_agents"]
        if isinstance(raw_agents, list):
            valid = [a.lower().strip() for a in raw_agents if isinstance(a, str)]
            valid = [a for a in valid if a in ALL_AGENTS]
            if valid:
                config.enabled_agents = valid
                logger.info("Enabled agents: %s", valid)
            else:
                logger.warning("No valid agents in enabled_agents — using all")
        else:
            logger.warning("enabled_agents must be a list — using all")

    # ignore
    if "ignore" in data:
        raw_ignore = data["ignore"]
        if isinstance(raw_ignore, list):
            config.ignore = [str(p) for p in raw_ignore]
            logger.info("Ignore patterns: %s", config.ignore)
        else:
            logger.warning("ignore must be a list — skipping")

    # threshold
    if "threshold" in data:
        raw_thresh = str(data["threshold"]).lower().strip()
        if raw_thresh in VALID_THRESHOLDS:
            config.threshold = raw_thresh
            logger.info("Threshold: %s", config.threshold)
        else:
            logger.warning("Invalid threshold '%s' — using 'suggestion'", raw_thresh)

    # max_comments
    if "max_comments" in data:
        try:
            mc = int(data["max_comments"])
            if 1 <= mc <= 50:
                config.max_comments = mc
                logger.info("Max comments: %d", mc)
            else:
                logger.warning("max_comments must be 1-50 — using 20")
        except (ValueError, TypeError):
            logger.warning("max_comments must be int — using 20")

    # custom_rules
    if "custom_rules" in data:
        raw_rules = data["custom_rules"]
        if isinstance(raw_rules, list):
            config.custom_rules = [str(r) for r in raw_rules if r]
            logger.info("Custom rules: %d loaded", len(config.custom_rules))
        else:
            logger.warning("custom_rules must be a list — skipping")

    return config
