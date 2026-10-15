/** Query-key factory: tiền tố = tên miền, khớp phần tử `invalidates` của @operation. */
type KeyFn = (...args: never[]) => readonly unknown[];

export function mkKeys<const N extends string, M extends Record<string, KeyFn>>(
  ns: N,
  map: M,
): { all: readonly [N] } & { [K in keyof M]: (...args: Parameters<M[K]>) => readonly unknown[] } {
  const out: Record<string, unknown> = { all: [ns] as const };
  for (const [name, fn] of Object.entries(map)) {
    out[name] = (...args: never[]) => [ns, ...fn(...args)];
  }
  return out as never;
}
