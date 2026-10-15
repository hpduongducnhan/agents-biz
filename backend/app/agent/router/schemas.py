"""Đầu ra có cấu trúc của router: 0–3 bước `{agent, task}` + câu hỏi lại (nếu mơ hồ)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RouteStep(BaseModel):
    """Một bước: chuyên gia xử lý + phần việc của bước, viết lại ngắn, đủ chi tiết (việc gì, của ai, khi nào)."""

    agent: str = Field(description="mã chuyên gia trong bảng (vd general, tasks)")
    task: str = Field(default="", description="phần việc của bước này")


class RouteDecision(BaseModel):
    """Chọn chuyên gia cho tin nhắn mới nhất. Mơ hồ hẳn → steps rỗng + clarify."""

    steps: list[RouteStep] = Field(default_factory=list, max_length=3)
    clarify: str | None = Field(default=None, description="câu hỏi lại khi không rõ người dùng muốn gì")
