import sys
from .runtime import run_source

def main():
    if len(sys.argv) != 2:
        print("사용법: python -m goout.cli <program.goout>")
        sys.exit(1)
    path = sys.argv[1]
    if not path.endswith(".goout"):
        print("경고: 파일 확장자는 .goout 이어야 합니다.")
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    run_source(src)

if __name__ == "__main__":
    main()