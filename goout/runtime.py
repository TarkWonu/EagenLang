import re
from .errors import GoOutRuntimeError
from .parser import STR_RE, NUM_RE, ID_RE
import ast
import sys

# ... main 진입 전에(또는 모듈 import 시) 표준출력 UTF-8 고정
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

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

def truthy(v):
    return bool(v)

# 아주 간단한 표현식 평가기: + - * / / 비교 / 논리
BIN_OPS = {
    '+': lambda a,b: a + b,
    '-': lambda a,b: a - b,
    '*': lambda a,b: a * b,
    '/': lambda a,b: a / b,
    '==': lambda a,b: a == b,
    '!=': lambda a,b: a != b,
    '<':  lambda a,b: a <  b,
    '<=': lambda a,b: a <= b,
    '>':  lambda a,b: a >  b,
    '>=': lambda a,b: a >= b,
    '&&': lambda a,b: truthy(a) and truthy(b),
    '||': lambda a,b: truthy(a) or  truthy(b),
}

UN_OPS = {
    '!': lambda a: not truthy(a),
}

BIN_PATTERN = re.compile(r'^(.*)\s*(\|\||&&|==|!=|<=|>=|<|>|[+\-*/])\s*(.*)$')

def eval_expr(expr: str, env: Env):
    expr = expr.strip()
    # 괄호
    if expr.startswith('(') and expr.endswith(')'):
        # 단순 괄호 제거(균형 가정)
        depth=0; ok=True
        for i,ch in enumerate(expr):
            if ch=='"': break
            if ch=='(' : depth+=1
            if ch==')' : depth-=1; 
            if depth==0 and i!=len(expr)-1: ok=False; break
        if ok:
            return eval_expr(expr[1:-1], env)

    # 문자열
    if STR_RE.fullmatch(expr):
    # 따옴표 포함된 리터럴 전체를 파이썬이 안전하게 해석
        return ast.literal_eval(expr)
    # 숫자
    if NUM_RE.fullmatch(expr):
        return float(expr) if '.' in expr else int(expr)
    # 식별자
    if ID_RE.fullmatch(expr):
        return env.get(expr)

    # 이항/논리
    m = BIN_PATTERN.match(expr)
    if m:
        left, op, right = m.group(1).strip(), m.group(2), m.group(3).strip()
        # 우선순위 간단 처리: 재귀적으로 오른쪽을 먼저 최대한 분해
        # (좌결합 보장하려면 더 정교한 파서 필요하지만 여기선 충분)
        a = eval_expr(left, env)
        b = eval_expr(right, env)
        if op in BIN_OPS:
            # 문자열 + 숫자 결합 허용
            if op == '+' and (isinstance(a,str) or isinstance(b,str)):
                return str(a) + str(b)
            return BIN_OPS[op](a,b)

    # 단항
    if expr.startswith('!'):
        return UN_OPS['!'](eval_expr(expr[1:], env))

    raise GoOutRuntimeError(f"지원되지 않는 표현식: {expr}")

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
            else: env.set(name, val)
        elif kind == "for":
            var, start_e, end_e, body = stmt[1], stmt[2], stmt[3], stmt[4]
            start = eval_expr(start_e, env)
            end   = eval_expr(end_e, env)
            if not (isinstance(start,int) and isinstance(end,int)):
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
            for p,a in zip(params, args):
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
    from .parser import parse_program
    ast = parse_program(src)
    env = Env()
    run_ast(ast, env)
