/** Token bucket cho mỗi socket: `capacity` event, hồi đầy sau `windowMs`. */

export class TokenBucket {
  private readonly capacity: number;
  private readonly windowMs: number;
  private tokens: number;
  private last: number | null = null;

  constructor(capacity: number, windowMs: number) {
    this.capacity = capacity;
    this.windowMs = windowMs;
    this.tokens = capacity;
  }

  take(now: number = Date.now()): boolean {
    if (this.last !== null) {
      this.tokens = Math.min(this.capacity, this.tokens + ((now - this.last) * this.capacity) / this.windowMs);
    }
    this.last = now;
    if (this.tokens < 1) return false;
    this.tokens -= 1;
    return true;
  }
}
