"""Numeric reversible encoding helper.

Python port of ``inc/adapters/XDeode.php`` (深秋的竹子) — a reversible
cipher that only supports numbers, suitable for obfuscating database id
fields or building numeric URLs.

Scheme: marker length + padding + digit substitution. The 62 shuffled
alphabet chars are split into: first ``length`` chars marking the digit
count, the next 10 substituting digits 0-9, the rest substituting
padding digits derived from ``nums / key``.

Port notes: PHP's precision-14 float-to-string conversion is reproduced
with ``%.14g``; padding chars are never validated by ``decode``, so
round trips are exact regardless of float formatting. As in the
original, numbers longer than ``length`` digits do not round-trip
(``begin`` marker runs out of the marker alphabet).
"""

from __future__ import annotations

__all__ = ["XDeode"]


class XDeode:
    """数字可逆加密类（用法: ``XDeode(9).encode(123)`` 与 ``decode``）."""

    strbase = "Flpvf70CsakVjqgeWUPXQxSyJizmNH6B1u3b8cAEKwTd54nRtZOMDhoG2YLrI"

    def __init__(self, length: int = 9, key: float = 2543.5415412812) -> None:
        self.key = key
        self.length = length
        self.codelen = self.strbase[:length]
        self.codenums = self.strbase[length : length + 10]
        self.codeext = self.strbase[length + 10 :]

    def encode(self, nums: int | str) -> str:
        """加密数字；返回 标记长度 + 补位 + 数字替换 的密文."""

        nums = str(nums)
        numslen = len(nums)
        # 密文第一位标记数字的长度
        begin = self.codelen[numslen - 1] if numslen - 1 < self.length else ""

        # 密文的扩展位
        extlen = self.length - numslen - 1
        temp = format(float(nums) / self.key, ".14g").replace(".", "")
        temp = temp[-extlen:]

        rtn = ""
        for char in temp:
            rtn += self.codeext[int(char)] if char.isdigit() else ""
        for char in nums:
            rtn += self.codenums[int(char)]
        return begin + rtn

    def decode(self, code: str) -> str:
        """解密数字字符串."""

        if not code:
            return ""
        begin = code[0]
        rtn = ""
        idx = self.codelen.find(begin)
        if idx != -1:
            num_len = idx + 1
            for char in code[-num_len:]:
                pos = self.codenums.find(char)
                if pos != -1:
                    rtn += str(pos)
        return rtn
