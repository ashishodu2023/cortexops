"""Slack and webhook alerting for CortexOps.

Fires alerts when eval runs complete with failures or when
task_completion drops below a configured threshold.

Configure via environment:
    CORTEXOPS_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
    CORTEXOPS_ALERT_THRESHOLD=0.90
    CORTEXOPS_ALERT_CHANNEL=#cortexops-alerts
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass
class AlertPayload:
    project: str
    run_id: str
    task_completion_rate: float
    tool_accuracy: float
    passed: int
    failed: int
    total_cases: int
    regressions: int
    failed_cases: list[dict[str, Any]]
    environment: str = "production"


class SlackAlerter:
    """Post eval result alerts to a Slack webhook.

    Args:
        webhook_url:  Slack incoming webhook URL.
        threshold:    Alert if task_completion_rate drops below this value.
        channel:      Override the webhook's default channel.
    """

    def __init__(
        self,
        webhook_url: str | None = None,
        threshold: float = 0.90,
        channel: str | None = None,
    ) -> None:
        self.webhook_url = webhook_url or os.getenv("CORTEXOPS_SLACK_WEBHOOK_URL")
        self.threshold = threshold
        self.channel = channel or os.getenv("CORTEXOPS_ALERT_CHANNEL")

    def should_alert(self, payload: AlertPayload) -> bool:
        return (
            payload.failed > 0
            or payload.task_completion_rate < self.threshold
            or payload.regressions > 0
        )

    def send(self, payload: AlertPayload) -> bool:
        """Send alert. Returns True if sent, False if skipped or failed."""
        if not self.webhook_url:
            return False
        if not self.should_alert(payload):
            return False

        blocks = self._build_blocks(payload)
        return self._post({"blocks": blocks, **({"channel": self.channel} if self.channel else {})})

    def _build_blocks(self, p: AlertPayload) -> list[dict]:
        status_icon = "red_circle" if p.failed > 0 else "large_yellow_circle"
        tc_pct = f"{p.task_completion_rate:.1%}"
        regression_line = f"\n:chart_with_downwards_trend: *{p.regressions} regressions* vs baseline" if p.regressions else ""

        header = f":{status_icon}: *CortexOps eval alert — {p.project}*"

        failed_lines = ""
        for case in p.failed_cases[:5]:
            failed_lines += f"\n  • `{case['case_id']}` — {case.get('failure_kind', 'unknown')} (score {case.get('score', 0):.0f})"
        if len(p.failed_cases) > 5:
            failed_lines += f"\n  _...and {len(p.failed_cases) - 5} more_"

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Task completion*\n{tc_pct}"},
                    {"type": "mrkdwn", "text": f"*Tool accuracy*\n{p.tool_accuracy:.1f}/100"},
                    {"type": "mrkdwn", "text": f"*Cases*\n{p.passed} passed / {p.failed} failed"},
                    {"type": "mrkdwn", "text": f"*Environment*\n{p.environment}"},
                ],
            },
        ]

        if regression_line or failed_lines:
            body = f"{regression_line}\n*Failed cases:*{failed_lines}" if failed_lines else regression_line
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body.strip()}})

        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "View run"},
                "url": f"https://app.cortexops.ai/evals/{p.run_id}",
                "style": "danger" if p.failed > 0 else "primary",
            }],
        })

        return blocks

    def _post(self, body: dict) -> bool:
        try:
            import httpx
            r = httpx.post(self.webhook_url, json=body, timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False


class WebhookAlerter:
    """Generic HTTP webhook for PagerDuty, OpsGenie, custom endpoints."""

    def __init__(self, url: str | None = None, secret: str | None = None) -> None:
        self.url = url or os.getenv("CORTEXOPS_WEBHOOK_URL")
        self.secret = secret or os.getenv("CORTEXOPS_WEBHOOK_SECRET")

    def send(self, payload: AlertPayload) -> bool:
        if not self.url:
            return False
        try:
            import httpx
            headers = {"Content-Type": "application/json"}
            if self.secret:
                headers["X-CortexOps-Signature"] = self._sign(payload)
            r = httpx.post(self.url, json=self._serialize(payload), headers=headers, timeout=5.0)
            return r.status_code < 300
        except Exception:
            return False

    def _serialize(self, p: AlertPayload) -> dict:
        return {
            "event": "eval.completed",
            "project": p.project,
            "run_id": p.run_id,
            "task_completion_rate": p.task_completion_rate,
            "tool_accuracy": p.tool_accuracy,
            "passed": p.passed,
            "failed": p.failed,
            "regressions": p.regressions,
            "environment": p.environment,
        }

    def _sign(self, p: AlertPayload) -> str:
        import hashlib
        import hmac
        body = json.dumps(self._serialize(p), sort_keys=True).encode()
        return hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()


def send_eval_alerts(payload: AlertPayload) -> dict[str, bool]:
    """Send all configured alerts. Returns dict of alerter -> success."""
    slack = SlackAlerter()
    webhook = WebhookAlerter()
    return {
        "slack": slack.send(payload),
        "webhook": webhook.send(payload),
    }
