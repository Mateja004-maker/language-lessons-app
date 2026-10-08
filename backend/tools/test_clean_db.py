"""Svi testovi na PRAZNOJ probnoj bazi (čisto okruženje), bez diranja prave baze.

    python tools/test_clean_db.py [--database language_learning_test] [--keep] [--only verify_x ...]

(iz foldera backend/). Koraci:
  1. pravi novu bazu (ime MORA da završava na "_test", mora se razlikovati od
     MYSQL_DATABASE iz .env i ne sme već da postoji);
  2. učitava db/schema.sql i db/reference_data.sql;
  3. upisuje izmišljene podatke (tools/seed_test_data.py);
  4. pokreće tests/test_*.py i tests/verify_*.py, svaki u posebnom procesu.
     verify_* testovi se pokreću kroz omotač koji posle učitavanja .env
     preusmeri MYSQL_DATABASE na probnu bazu i proveri SELECT DATABASE() pre
     testa. Kod aplikacije i testova se ne menja; app.get_db_connection čita
     MYSQL_DATABASE pri svakom pozivu;
  5. briše probnu bazu (osim uz --keep) i ispisuje rezime.

Napomena: test koji bi sam pokrenuo NOVI Python proces koji importuje app
ponovo bi učitao .env i radio nad pravom bazom - testovi zato zovu alate u
istom procesu.
Izlazni kod: 0 = svi testovi prošli, 1 = bar jedan pao, 2 = probna baza se ne može napraviti.
"""
import argparse
import glob
import os
import subprocess
import sys
import time

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "tools"))

import app as app_module  # noqa: E402  (učitava backend/.env)
import mysql.connector  # noqa: E402

import seed_test_data  # noqa: E402

SQL_FILES = (os.path.join(ROOT, "db", "schema.sql"), os.path.join(ROOT, "db", "reference_data.sql"))
NOISE = ("InsecureKeyLengthWarning", "decoded = self", "_jws.encode", "warnings.warn")

BOOTSTRAP = r"""
import os, runpy, sys
backend, target, path = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, backend)
import app                      # učitava .env (override=True) ...
os.environ["MYSQL_DATABASE"] = target   # ... pa tek onda preusmerenje na probnu bazu
conn = app.get_db_connection()
cur = conn.cursor()
cur.execute("SELECT DATABASE()")
actual = cur.fetchone()[0]
conn.close()
if actual != target:
    print(f"ODBIJENO: test bi radio nad bazom {actual!r}, a ne {target!r}")
    sys.exit(3)
sys.argv = [path]
runpy.run_path(path, run_name="__main__")
"""


def server_connection(database=None):
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"), port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER"), password=os.getenv("MYSQL_PASSWORD", ""),
        **({"database": database} if database else {}),
    )


def sql_statements(path):
    """Naredbe iz .sql fajla (po jedna u svakom bloku koji se završava sa ';' na kraju reda)."""
    statement = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not statement and (not stripped or stripped.startswith("--")):
                continue
            statement.append(line)
            if stripped.endswith(";"):
                yield "".join(statement)
                statement = []
    if "".join(statement).strip():
        yield "".join(statement)


def check_name(target, real):
    if not target.endswith("_test"):
        return "ime probne baze mora da završava na _test"
    if target == real:
        return "probna baza ne sme biti ista kao MYSQL_DATABASE iz .env"
    if not target.replace("_", "").isalnum():
        return "ime probne baze sme da sadrži samo slova, brojeve i _"
    return None


def create_database(target):
    conn = server_connection()
    cur = conn.cursor()
    try:
        cur.execute("SHOW DATABASES LIKE %s", (target,))
        if cur.fetchone():
            raise RuntimeError(f"baza {target} već postoji - obrišite je ručno ili izaberite drugo ime")
        cur.execute(f"CREATE DATABASE `{target}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci")
    finally:
        cur.close()
        conn.close()
    conn = server_connection(target)
    cur = conn.cursor()
    try:
        count = 0
        for path in SQL_FILES:
            for statement in sql_statements(path):
                cur.execute(statement)
                count += 1
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s", (target,))
        tables = cur.fetchone()[0]
        seed_test_data.seed(conn)
    finally:
        cur.close()
        conn.close()
    return count, tables


def drop_database(target, real):
    if check_name(target, real):  # dodatna zaštita pre DROP
        raise RuntimeError(f"odbijeno brisanje baze {target}")
    conn = server_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"DROP DATABASE IF EXISTS `{target}`")
    finally:
        cur.close()
        conn.close()


def summary_line(output):
    """Zbirni red testa: 'Ukupno: ...' / 'N/N OK' (verify) ili 'Ran N tests ... OK' (unittest)."""
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    ran = next((l for l in reversed(lines) if l.startswith("Ran ")), None)
    if ran:
        status = next((l for l in reversed(lines) if l.startswith(("OK", "FAILED"))), "")
        return f"{ran.split(' in ')[0]}: {status}"
    for line in reversed(lines):
        if line.startswith("Ukupno:") or line.endswith(" OK"):
            return line
    return lines[-1] if lines else ""


def run_tests(target, only=None):
    tests = sorted(glob.glob(os.path.join(BACKEND, "tests", "test_*.py"))) + \
        sorted(glob.glob(os.path.join(BACKEND, "tests", "verify_*.py")))
    if only:
        tests = [t for t in tests if os.path.splitext(os.path.basename(t))[0] in only]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    results = []
    for path in tests:
        name = os.path.splitext(os.path.basename(path))[0]
        if name.startswith("verify_"):
            cmd = [sys.executable, "-c", BOOTSTRAP, BACKEND, target, path]
        else:
            cmd = [sys.executable, path]
        started = time.time()
        proc = subprocess.run(cmd, cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        output = "\n".join(l for l in (proc.stdout + "\n" + proc.stderr).splitlines() if not any(n in l for n in NOISE))
        results.append((name, proc.returncode, summary_line(output), time.time() - started, output))
    return results


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python tools/test_clean_db.py")
    parser.add_argument("--database", default="language_learning_test", help="ime probne baze (mora da završava na _test)")
    parser.add_argument("--keep", action="store_true", help="ne briši probnu bazu na kraju")
    parser.add_argument("--only", nargs="*", help="samo ovi testovi (npr. verify_set_generation)")
    parser.add_argument("--verbose", action="store_true", help="ispiši ceo izlaz testova koji su pali")
    args = parser.parse_args(argv)

    real = os.getenv("MYSQL_DATABASE")
    problem = check_name(args.database, real)
    if problem:
        print(f"Odbijeno: {problem}.")
        return 2
    try:
        statements, tables = create_database(args.database)
    except Exception as e:
        print(f"Probna baza nije napravljena: {e}")
        if "već postoji" not in str(e):
            drop_database(args.database, real)
        return 2
    print(f"Probna baza {args.database}: {statements} SQL naredbi, {tables} tabela.\n")

    try:
        results = run_tests(args.database, args.only)
    finally:
        if args.keep:
            print(f"\nProbna baza {args.database} je ZADRŽANA (--keep).")
        else:
            drop_database(args.database, real)

    width = max(len(r[0]) for r in results) if results else 10
    for name, code, line, seconds, _ in results:
        print(f"{'OK' if code == 0 else 'PALO':4}  {name:<{width}}  {line}  ({seconds:.0f} s)")
    failed = [r for r in results if r[1] != 0]
    if args.verbose:
        for name, code, _, _, output in failed:
            print(f"\n===== {name} (izlazni kod {code}) =====\n{output}")
    if not args.keep:
        print(f"\nProbna baza {args.database} obrisana.")
    print(f"Prošlo: {len(results) - len(failed)}/{len(results)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
