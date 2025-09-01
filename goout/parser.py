import re
from .errors import GoOutSyntaxError

# 시작 / 끝 규칙
RE_START = re.compile(r'^\s*시작!\s*$')
RE_END   = re.compile(r'^\s*장한울을 혁명적으로 특검해야 한다\s*$')

# 런타임에서도 씀
STR_RE = re.compile(r'"([^"\\]|\\.)*"')
NUM_RE = re.compile(r'\d+(?:\.\d+)?')
ID_RE  = re.compile(r'[A-Za-z_가-힣]\w*')

def parse_program(src: str):
    lines = [l.rstrip() for l in src.splitlines()]
    nz = [i for i, l in enumerate(lines) if l.strip() != '']
    if not nz:
        raise GoOutSyntaxError("빈 프로그램")
    if not RE_START.match(lines[nz[0]]):
        raise GoOutSyntaxError('프로그램은 "시작!"으로 시작해야 합니다.')
    if not RE_END.match(lines[nz[-1]]):
        raise GoOutSyntaxError('프로그램은 "장한울을 혁명적으로 특검해야 한다"로 끝나야 합니다.')

    # 본문(첫/끝 제거)
    body = lines[nz[0] + 1:nz[-1]]
    i = 0

    # 콤마 분리 (문자열 안의 , 무시)
    def split_commas(s: str):
        out, buf, in_str, esc = [], [], False, False
        for ch in s:
            if in_str:
                buf.append(ch)
                if esc:
                    esc = False
                elif ch == '\\':
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                    buf.append(ch)
                elif ch == ',':
                    out.append(''.join(buf).strip()); buf = []
                else:
                    buf.append(ch)
        tail = ''.join(buf).strip()
        if tail != '':
            out.append(tail)
        return out

    def parse_block():
        nonlocal i
        stmts = []
        while i < len(body):
            orig = body[i]
            line = orig.strip()

            # 한 줄에 '}'와 다음 토큰이 같이 있는 경우 분해
            m_split = re.match(r'^\s*\}\s*(.+)$', orig)
            if m_split:
                body[i] = '}'
                body.insert(i + 1, m_split.group(1))
                line = '}'

            if line == '}':
                i += 1
                break

            if not line:
                i += 1
                continue

            # 만약 / 디떨이 아니다?!
            m = re.match(r'^GO척결\.만약\s*\((.*)\)\s*\{\s*$', line)
            if m:
                cond = m.group(1).strip()
                i += 1
                then_body = parse_block()
                else_body = None
                if i < len(body):
                    nxt = body[i].strip()
                    if re.match(r'^GO척결\.디떨이 아니다\?!\s*\{\s*$', nxt):
                        i += 1
                        else_body = parse_block()
                stmts.append(("if", cond, then_body, else_body))
                continue

            # 반복<var>(start, end) { ... }
            m = re.match(r'^GO척결\.반복([A-Za-z_가-힣]\w*)\s*\((.*)\)\s*\{\s*$', line)
            if m:
                var = m.group(1)
                args = [a.strip() for a in split_commas(m.group(2))]
                if len(args) != 2:
                    raise GoOutSyntaxError(f"반복{var}는 (시작,끝) 2개 인자 필요")
                i += 1
                inner = parse_block()
                stmts.append(("for", var, args[0], args[1], inner))
                continue

            # 함수 정의
            m = re.match(r'^GO척결\.함수\s+([A-Za-z_가-힣]\w*)\s*\((.*)\)\s*\{\s*$', line)
            if m:
                fname = m.group(1)
                params = [p.strip() for p in split_commas(m.group(2))]
                if len(params) == 1 and params[0] == '':
                    params = []
                i += 1
                inner = parse_block()
                stmts.append(("def", fname, params, inner))
                continue

            # 출력
            m = re.match(r'^GO척결\.출력\s*\((.*)\)\s*$', line)
            if m:
                stmts.append(("print", m.group(1).strip()))
                i += 1
                continue

            # 입력: GO척결.입력(변수명, "프롬프트", "정수|실수|문자열")
            m = re.match(r'^GO척결\.입력\s*\(\s*([A-Za-z_가-힣]\w*)\s*(?:,(.*))?\)\s*$', line)
            if m:
                name = m.group(1)
                rest = (m.group(2) or "").strip()
                args = [a.strip() for a in split_commas(rest)] if rest else []
                # args[0]=프롬프트(표현식, 옵션), args[1]=타입 문자열(옵션)
                stmts.append(("input", name, args))
                i += 1
                continue

            # 함수 호출
            m = re.match(r'^GO척결\.호출\s*\(\s*([A-Za-z_가-힣]\w*)\s*(?:,(.*))?\)\s*$', line)
            if m:
                fname = m.group(1)
                rest = (m.group(2) or "").strip()
                args = [a.strip() for a in split_commas(rest)] if rest else []
                stmts.append(("call", fname, args))
                i += 1
                continue

            # 변수/대입
            m = re.match(r'^GO척결\.(변수|대입)\s+([A-Za-z_가-힣]\w*)\s*=\s*(.+)$', line)
            if m:
                is_decl = (m.group(1) == '변수')
                name = m.group(2)
                expr = m.group(3).strip()
                stmts.append(("assign", name, expr, is_decl))
                i += 1
                continue

            # 중괄호 단독 블록
            if line == '{':
                i += 1
                inner = parse_block()
                stmts.append(("block", inner))
                continue

            raise GoOutSyntaxError(f"알 수 없는 구문: {line}")

        return stmts

    i = 0
    ast = parse_block()
    if i < len(body):
        raise GoOutSyntaxError("블록 정합성 오류")
    return ast
