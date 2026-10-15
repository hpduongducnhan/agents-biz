-- Hạn mức tin nhắn theo cửa sổ: kiểm mọi khoá rồi mới cộng — vượt khoá nào thì không cộng khoá
-- nào. KEYS[i] = bộ đếm (phút / giờ / ngày của agent, rồi của tài khoản); ARGV[i] = trần (0 = không giới hạn);
-- ARGV[#KEYS + i] = TTL giây. Trả chỉ số khoá vượt đầu tiên, 0 = đã cộng.
for i = 1, #KEYS do
  local cap = tonumber(ARGV[i])
  if cap > 0 and tonumber(redis.call('GET', KEYS[i]) or '0') >= cap then
    return i
  end
end
for i = 1, #KEYS do
  redis.call('INCR', KEYS[i])
  redis.call('EXPIRE', KEYS[i], tonumber(ARGV[#KEYS + i]))
end
return 0
