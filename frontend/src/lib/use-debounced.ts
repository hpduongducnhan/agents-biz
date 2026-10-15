import { useEffect, useState } from "react";

/** Giá trị trễ `ms` sau lần đổi cuối — ô tìm không gọi API theo từng phím. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}
