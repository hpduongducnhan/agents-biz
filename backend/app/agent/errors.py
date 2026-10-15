"""Mã lỗi agent — 6001–6099. 6016 do miền credential đăng ký."""

from __future__ import annotations

from app.core.errors import register_errors

AGENT_ERRORS: dict[int, str] = {
    6001: "Too many messages — try again later",
    6002: "Daily token limit reached",
    6003: "Agent not found or not available to you",
    6004: "Chat session not found",
    6005: "This chat session already has a running turn",
    6006: "Run not found",
    6007: "Run is not waiting for approval",
    6008: "Approval already decided or expired",
    6009: "The assistant has no model configured",
    6010: "No API key available",
    6011: "The model provider returned an error",
    6012: "The turn took too long",
    6013: "The turn exceeded the maximum number of steps",
    6014: "The turn was cancelled",
    6015: "The turn was interrupted — please send your message again",
    6017: "Invalid hook configuration",
    6018: "Hook webhook failed",
    6019: "Blocked by an assistant rule",
    6020: "Key does not belong to the model's provider",
    6021: "Too many hand-offs in one turn",
    6022: "You are temporarily blocked from the assistant",
    6023: "The assistant is turned off for your organization",
}
register_errors(AGENT_ERRORS, owner="agent")
