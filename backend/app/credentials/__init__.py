"""Credential dùng chung (key provider LLM, khoá webhook…): mã hoá at-rest bằng Fernet (`CREDENTIAL_KEYS`), API không
bao giờ trả giá trị — chỉ `masked_hint`. Nạp gói = đăng ký mã lỗi 6016."""

from app.credentials import errors as errors  # noqa: F401
