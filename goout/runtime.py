import sys
import ast
from .parser import STR_RE, NUM_RE, ID_RE
try:
    from .errors import GoOutRuntimeError
except Exception:
    class GoOutRuntimeError(RuntimeError):
        ...

# 콘솔 UTF-8 보장 (Windows 포함)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stdin, "reconfigure"):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass


class Env(dict):
    """
    변수/함수 저장용 환경. 체이닝 지원.
    """
    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent
        self.funcs = {}

    def get(self, k):
        if k in self:
            return self[k]
        if self.parent:
            return self.parent.get(k)
        raise GoOutRuntimeError(f"변수 {k}가 정의되지 않았습니다.")

    def set(self, k, v):
        scope = self
        while scope is not None:
            if k in scope:
                scope[k] = v
                return
            scope = scope.parent
        # 상위에 없으면 현재에 생성
        self[k] = v


def truthy(v):
    return bool(v)


# --------------------------
#  표현식 토크나이저 & 파서
# --------------------------

# 허용 연산자 (우선순위: 낮음→높음)
# or( || ), and( && ), equality, compare, add, mul, unary(!, -)
_OP2 = ("||", "&&", "==", "!=", "<=", ">=", "<", ">", "+", "-", "*", "/")
_UNARY = ("!", "-")

def _tokenize(expr: str):
    """
    공백을 무시하고 토큰 스트림 생성.
    토큰: STRING, NUMBER, IDENT, OP, LPAREN, RPAREN
    """
    s = expr
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]

        # 공백
        if ch.isspace():
            i += 1
            continue

        # 문자열 (큰따옴표, 이스케이프 지원)
        if ch == '"':
            j = i + 1
            esc = False
            while j < n:
                c = s[j]
                if esc:
                    esc = False
                    j += 1
                    continue
                if c == '\\':
                    esc = True
                    j += 1
                    continue
                if c == '"':
                    lit = s[i:j+1]  # 따옴표 포함
                    yield ("STRING", lit)
                    i = j + 1
                    break
                j += 1
            else:
                raise GoOutRuntimeError("문자열 리터럴이 닫히지 않았습니다.")
            continue

        # 괄호
        if ch == '(':
            yield ("LPAREN", ch); i += 1; continue
        if ch == ')':
            yield ("RPAREN", ch); i += 1; continue

        # 2글자 연산자 우선
        if i + 1 < n:
            two = s[i:i+2]
            if two in ("||", "&&", "==", "!=", "<=", ">="):
                yield ("OP", two)
                i += 2
                continue

        # 1글자 연산자
        if ch in "+-*/<>!":
            yield ("OP", ch)
            i += 1
            continue

        # 숫자
        if ch.isdigit():
            j = i + 1
            dot_seen = False
            while j < n and (s[j].isdigit() or (s[j] == '.' and not dot_seen)):
                if s[j] == '.':
                    dot_seen = True
                j += 1
            yield ("NUMBER", s[i:j])
            i = j
            continue

        # 식별자 (한글 포함)
        # ID_RE: [A-Za-z_가-힣]\w*
        # 여기서는 간단히 ID_RE 적용
        j = i + 1
        while j <= n and ID_RE.fullmatch(s[i:j] or ""):
            j += 1
        j -= 1
        if j > i and ID_RE.fullmatch(s[i:j]):
            yield ("IDENT", s[i:j])
            i = j
            continue

        raise GoOutRuntimeError(f"알 수 없는 토큰 시작: {s[i:i+10]!r}")

    yield ("EOF", "")


class _TokStream:
    def __init__(self, tokens):
        self.toks = list(tokens)
        self.i = 0

    def peek(self):
        return self.toks[self.i]

    def match(self, kind=None, value=None):
        t = self.peek()
        if kind is not None and t[0] != kind:
            return None
        if value is not None and t[1] != value:
            return None
        self.i += 1
        return t

    def expect(self, kind, value=None, msg="토큰이 필요합니다"):
        t = self.match(kind, value)
        if not t:
            cur = self.peek()
            raise GoOutRuntimeError(f"{msg}. 현재: {cur}")
        return t


def eval_expr(expr: str, env: Env):
    """
    재귀하강 파서로 표현식 평가.
    - 문자열은 ast.literal_eval로 안전하게 파싱
    - 숫자: int/float
    - 식별자: env에서 조회
    - '+'는 문자열/숫자 혼합 허용 (문자열 결합)
    - 단락 평가: &&, ||
    """
    ts = _TokStream(_tokenize(expr))

    def parse_expr():
        return parse_or()

    def parse_or():
        left = parse_and()
        while True:
            t = ts.match("OP", "||")
            if not t:
                break
            # 단락 평가
            if truthy(left):
                # left가 true면 오른쪽 무시하고 True
                _ = skip_until_higher_prec(parse_and)  # 그래도 구문소비 필요
                left = True
            else:
                right = parse_and()
                left = truthy(right)
        return left

    def parse_and():
        left = parse_equality()
        while True:
            t = ts.match("OP", "&&")
            if not t:
                break
            # 단락 평가
            if not truthy(left):
                _ = skip_until_higher_prec(parse_equality)  # 소비
                left = False
            else:
                right = parse_equality()
                left = truthy(right)
        return left

    def parse_equality():
        left = parse_compare()
        while True:
            t = ts.peek()
            if t[0] == "OP" and t[1] in ("==", "!="):
                op = ts.match("OP")[1]
                right = parse_compare()
                if op == "==":
                    left = left == right
                else:
                    left = left != right
            else:
                break
        return left

    def parse_compare():
        left = parse_add()
        while True:
            t = ts.peek()
            if t[0] == "OP" and t[1] in ("<", "<=", ">", ">="):
                op = ts.match("OP")[1]
                right = parse_add()
                if op == "<":
                    left = left < right
                elif op == "<=":
                    left = left <= right
                elif op == ">":
                    left = left > right
                else:
                    left = left >= right
            else:
                break
        return left

    def parse_add():
        left = parse_mul()
        while True:
            t = ts.peek()
            if t[0] == "OP" and t[1] in ("+", "-"):
                op = ts.match("OP")[1]
                right = parse_mul()
                if op == "+":
                    # 문자열/숫자 혼합 허용
                    if isinstance(left, str) or isinstance(right, str):
                        left = str(left) + str(right)
                    else:
                        left = left + right
                else:
                    left = left - right
            else:
                break
        return left

    def parse_mul():
        left = parse_unary()
        while True:
            t = ts.peek()
            if t[0] == "OP" and t[1] in ("*", "/"):
                op = ts.match("OP")[1]
                right = parse_unary()
                if op == "*":
                    left = left * right
                else:
                    left = left / right
            else:
                break
        return left

    def parse_unary():
        t = ts.peek()
        if t[0] == "OP" and t[1] in _UNARY:
            op = ts.match("OP")[1]
            val = parse_unary()
            if op == "!":
                return not truthy(val)
            else:  # '-'
                if isinstance(val, (int, float)):
                    return -val
                raise GoOutRuntimeError("숫자에만 음수(-)를 적용할 수 있습니다.")
        return parse_primary()

    def parse_primary():
        t = ts.peek()
        if t[0] == "LPAREN":
            ts.match("LPAREN")
            v = parse_expr()
            ts.expect("RPAREN", msg="')'가 필요합니다")
            return v
        if t[0] == "STRING":
            tok = ts.match("STRING")[1]
            # 안전 문자열 파싱
            return ast.literal_eval(tok)
        if t[0] == "NUMBER":
            tok = ts.match("NUMBER")[1]
            return float(tok) if '.' in tok else int(tok)
        if t[0] == "IDENT":
            name = ts.match("IDENT")[1]
            return env.get(name)
        raise GoOutRuntimeError(f"표현식이 필요합니다: {t}")

    def skip_until_higher_prec(next_parser):
        """
        and/or 단락 평가 시, 오른쪽 서브트리를 '평가하지 않지만'
        구문만 소비해야 하는 경우가 있음.
        간단히 next_parser를 호출해 구조를 소비만 수행.
        """
        return next_parser()

    result = parse_expr()
    end = ts.peek()
    if end[0] != "EOF":
        raise GoOutRuntimeError(f"표현식 끝에 불필요한 토큰: {end}")
    return result


# --------------------------
#        AST 실행기
# --------------------------

def run_ast(ast, env: Env):
    for stmt in ast:
        kind = stmt[0]

        if kind == "print":
            val = eval_expr(stmt[1], env)
            # 표기 형식: None → 'nil', True/False → 'true'/'false' 로 출력하고 싶다면 아래 주석 해제
            # if val is None: print("nil"); continue
            # if isinstance(val, bool): print("true" if val else "false"); continue
            print(val)

        elif kind == "assign":
            name, expr, is_decl = stmt[1], stmt[2], stmt[3]
            val = eval_expr(expr, env)
            if is_decl:
                env[name] = val
            else:
                env.set(name, val)

        elif kind == "for":
            var, start_e, end_e, body = stmt[1], stmt[2], stmt[3], stmt[4]
            start = eval_expr(start_e, env)
            end   = eval_expr(end_e, env)
            if not (isinstance(start, int) and isinstance(end, int)):
                raise GoOutRuntimeError("반복 구간은 정수여야 합니다.")
            for i in range(start, end):
                local = Env(parent=env)
                local[var] = i
                run_ast(body, local)

        elif kind == "def":
            fname, params, body = stmt[1], stmt[2], stmt[3]
            env.funcs[fname] = (params, body)

        elif kind == "call":
            fname, args = stmt[1], stmt[2]
            if fname not in env.funcs:
                raise GoOutRuntimeError(f"함수 {fname}가 정의되지 않았습니다.")
            params, body = env.funcs[fname]
            if len(params) != len(args):
                raise GoOutRuntimeError(
                    f"함수 {fname} 인자 개수 불일치: {len(params)} 필요, {len(args)} 제공"
                )
            local = Env(parent=env)
            for p, a in zip(params, args):
                local[p] = eval_expr(a, env)
            run_ast(body, local)

        elif kind == "if":
            cond, then_body, else_body = stmt[1], stmt[2], stmt[3]
            if truthy(eval_expr(cond, env)):
                run_ast(then_body, env)
            elif else_body:
                run_ast(else_body, env)

        elif kind == "block":
            local = Env(parent=env)
            run_ast(stmt[1], local)

        else:
            raise GoOutRuntimeError(f"알 수 없는 문장 타입: {kind}")


def run_source(src: str):
    """
    문자열 소스 전체 실행
    """
    from .parser import parse_program
    ast_root = parse_program(src)
    env = Env()
    run_ast(ast_root, env)
