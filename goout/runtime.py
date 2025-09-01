import sys
import ast
from .parser import STR_RE, NUM_RE, ID_RE
try:
    from .errors import GoOutRuntimeError
except Exception:
    class GoOutRuntimeError(RuntimeError):
        ...

# 콘솔 UTF-8 보장
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
if hasattr(sys.stdin, "reconfigure"):
    try: sys.stdin.reconfigure(encoding="utf-8")
    except Exception: pass


class Env(dict):
    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent
        self.funcs = {}

    def get(self, k):
        if k in self: return self[k]
        if self.parent: return self.parent.get(k)
        raise GoOutRuntimeError(f"변수 {k}가 정의되지 않았습니다.")

    def set(self, k, v):
        scope = self
        while scope is not None:
            if k in scope:
                scope[k] = v; return
            scope = scope.parent
        self[k] = v


def truthy(v): return bool(v)

# ------------- 토크나이저 -------------

_UNARY = ("!", "-")

def _tokenize(expr: str):
    """
    토큰: STRING, NUMBER, IDENT, OP, LPAREN, RPAREN, LBRACK, RBRACK, COMMA, EOF
    """
    s = expr
    i, n = 0, len(expr)
    while i < n:
        ch = s[i]

        if ch.isspace():
            i += 1; continue

        # 문자열
        if ch == '"':
            j = i + 1; esc = False
            while j < n:
                c = s[j]
                if esc: esc = False; j += 1; continue
                if c == '\\': esc = True; j += 1; continue
                if c == '"':
                    yield ("STRING", s[i:j+1]); i = j + 1; break
                j += 1
            else:
                raise GoOutRuntimeError("문자열 리터럴이 닫히지 않았습니다.")
            continue

        if ch == '(':
            yield ("LPAREN", ch); i += 1; continue
        if ch == ')':
            yield ("RPAREN", ch); i += 1; continue
        if ch == '[':
            yield ("LBRACK", ch); i += 1; continue
        if ch == ']':
            yield ("RBRACK", ch); i += 1; continue
        if ch == ',':
            yield ("COMMA", ch); i += 1; continue

        # 2글자 연산자
        if i + 1 < n and s[i:i+2] in ("||", "&&", "==", "!=", "<=", ">="):
            yield ("OP", s[i:i+2]); i += 2; continue

        # 1글자 연산자
        if ch in "+-*/<>!":
            yield ("OP", ch); i += 1; continue

        # 숫자
        if ch.isdigit():
            j = i + 1; dot = False
            while j < n and (s[j].isdigit() or (s[j] == '.' and not dot)):
                if s[j] == '.': dot = True
                j += 1
            yield ("NUMBER", s[i:j]); i = j; continue

        # 식별자 (한글 포함)
        j = i + 1
        while j <= n and ID_RE.fullmatch(s[i:j] or ""):
            j += 1
        j -= 1
        if j > i and ID_RE.fullmatch(s[i:j]):
            yield ("IDENT", s[i:j]); i = j; continue

        raise GoOutRuntimeError(f"알 수 없는 토큰 시작: {s[i:i+10]!r}")

    yield ("EOF", "")


class _TokStream:
    def __init__(self, tokens):
        self.toks = list(tokens)
        self.i = 0

    def peek(self): return self.toks[self.i]
    def match(self, kind=None, value=None):
        t = self.peek()
        if kind is not None and t[0] != kind: return None
        if value is not None and t[1] != value: return None
        self.i += 1; return t
    def expect(self, kind, value=None, msg="토큰이 필요합니다"):
        t = self.match(kind, value)
        if not t:
            cur = self.peek()
            raise GoOutRuntimeError(f"{msg}. 현재: {cur}")
        return t


# ------------- 표현식 파서/평가 -------------

def eval_expr(expr: str, env: Env):
    ts = _TokStream(_tokenize(expr))

    def parse_expr(): return parse_or()

    def parse_or():
        left = parse_and()
        while ts.match("OP", "||"):
            if truthy(left):
                _ = skip(parse_and)  # 구문만 소비
                left = True
            else:
                right = parse_and()
                left = truthy(right)
        return left

    def parse_and():
        left = parse_equality()
        while ts.match("OP", "&&"):
            if not truthy(left):
                _ = skip(parse_equality)
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
                left = (left == right) if op == "==" else (left != right)
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
                if   op == "<":  left = left <  right
                elif op == "<=": left = left <= right
                elif op == ">":  left = left >  right
                else:            left = left >= right
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
                left = left * right if op == "*" else left / right
            else:
                break
        return left

    def parse_unary():
        t = ts.peek()
        if t[0] == "OP" and t[1] in _UNARY:
            op = ts.match("OP")[1]
            val = parse_unary()
            if op == "!": return not truthy(val)
            if isinstance(val, (int, float)): return -val
            raise GoOutRuntimeError("숫자에만 음수(-) 적용 가능")
        return parse_postfix()

    def parse_postfix():
        val = parse_primary()
        while True:
            t = ts.peek()
            if t[0] == "LBRACK":  # 인덱싱
                ts.match("LBRACK")
                idx = parse_expr()
                ts.expect("RBRACK", msg="']'가 필요합니다")
                try:
                    val = val[idx]
                except Exception:
                    raise GoOutRuntimeError("인덱싱 오류")
            else:
                break
        return val

    def parse_primary():
        t = ts.peek()
        if t[0] == "LPAREN":
            ts.match("LPAREN")
            v = parse_expr()
            ts.expect("RPAREN", msg="')'가 필요합니다")
            return v
        if t[0] == "LBRACK":  # 배열 리터럴
            ts.match("LBRACK")
            arr = []
            if ts.peek()[0] != "RBRACK":
                while True:
                    arr.append(parse_expr())
                    if ts.match("COMMA"): continue
                    else: break
            ts.expect("RBRACK", msg="']'가 필요합니다")
            return arr
        if t[0] == "STRING":
            return ast.literal_eval(ts.match("STRING")[1])  # 안전 문자열
        if t[0] == "NUMBER":
            tok = ts.match("NUMBER")[1]
            return float(tok) if '.' in tok else int(tok)
        if t[0] == "IDENT":
            return env.get(ts.match("IDENT")[1])
        raise GoOutRuntimeError(f"표현식이 필요합니다: {t}")

    def skip(next_parser):  # and/or 단락 평가용
        return next_parser()

    result = parse_expr()
    if ts.peek()[0] != "EOF":
        raise GoOutRuntimeError(f"표현식 끝에 불필요한 토큰: {ts.peek()}")
    return result


# ------------- AST 실행 -------------

def run_ast(ast, env: Env):
    for stmt in ast:
        kind = stmt[0]

        if kind == "print":
            val = eval_expr(stmt[1], env)
            print(val)

        elif kind == "assign":
            name, expr, is_decl = stmt[1], stmt[2], stmt[3]
            val = eval_expr(expr, env)
            if is_decl: env[name] = val
            else:       env.set(name, val)

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
                raise GoOutRuntimeError(f"함수 {fname} 인자 개수 불일치: {len(params)} 필요, {len(args)} 제공")
            local = Env(parent=env)
            for p, a in zip(params, args):
                local[p] = eval_expr(a, env)
            run_ast(body, local)

        elif kind == "input":
            name, args = stmt[1], stmt[2]
            prompt = ""
            ty = "문자열"
            if len(args) >= 1 and args[0] != "":
                prompt = eval_expr(args[0], env)
            if len(args) >= 2 and args[1] != "":
                ty = eval_expr(args[1], env)
            try:
                s = input(str(prompt))
            except EOFError:
                s = ""
            val = s
            if isinstance(ty, str):
                t = ty.strip().lower()
                if t in ("정수", "int", "integer"):   val = int(s)
                elif t in ("실수", "float", "double"): val = float(s)
                # 문자열은 그대로
            env[name] = val

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
    from .parser import parse_program
    ast_root = parse_program(src)
    env = Env()
    run_ast(ast_root, env)
