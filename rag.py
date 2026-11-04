"""사내 지식 검색 (RAG)

knowledge/*.md (지표 정의서·운영 규칙 같은 사내 문서)를 소제목(##) 단위 조각으로 잘라 색인하고,
질문과 가까운 조각을 찾아 줌. 스키마만으로는 알 수 없는 "골든타임 응대율", "청약철회" 같은
사내 용어 정의를 에이전트에 넣기 위함.

검색 방식 (환경변수 RAG_MODE)
- hybrid (기본): 벡터 + 키워드. 점수 = 코사인 + 0.1 × BM25, 0.8 미만은 버림
  - 벡터 검색: 임베딩(문장 → 숫자 벡터) 코사인 유사도. "하루도 안 돼서 취소"처럼 바꿔 말한 질문을 잡음
  - 키워드 검색: BM25(한글은 두 글자씩 잘라 셈). "SLA", "ARPU" 같은 고유 용어를 정확히 잡음
- bm25: 키워드만. 임베딩 모델을 안 올려서 메모리가 늘지 않음 (메모리 512MB인 Render 무료용)
  hybrid는 서버 메모리가 135MB → 약 690MB (대부분 50만 단어 토크나이저)

python rag.py --build         벡터 색인 만들기 (knowledge.duckdb, hybrid 용)
python rag.py --eval          검색 적중률 점검 (API 호출 없음, 무료)
python rag.py "질문"           검색 결과 보기
"""
import math
import os
import re
import sys
import threading
from pathlib import Path

import duckdb

# 정적 임베딩 모델(트랜스포머 없이 단어 벡터 평균): 다국어, 256차원, CPU에서 빠름
# MiniLM(0.22GB)·mpnet(1GB)과 비교해 지식 문항 1순위 적중이 가장 높았음 (MiniLM 3/12, mpnet 8/12, potion 10/12)
MODEL = "minishlab/potion-multilingual-128M"
DIM = 256
KNOWLEDGE_DIR = Path("knowledge")
INDEX = Path("knowledge.duckdb")
MODEL_DIR = Path(".models")  # 모델 파일을 프로젝트 안에 받아 둠 (Docker 이미지에 같이 들어감)

MODE = os.environ.get("RAG_MODE", "hybrid")
TOP_K = 3
BM25_WEIGHT = 0.1
TERM_BONUS = 5.0  # 질문에 소제목(용어)이 통째로 들어 있으면 BM25 점수에 더함 ('순가입'이 '가입' 문서들에 묻히지 않게)
MIN_SCORE = {"hybrid": 0.8, "bm25": 3.0, "vector": -1}  # 이보다 낮은 조각은 넣지 않음 (rag.py --eval 로 정함)

_model = None
_con = None
_bm25 = None
_chunks = None
_lock = threading.RLock()  # embed() 안에서 embedder()를 또 잠그므로 재진입 가능한 잠금


def embedder():
    global _model
    with _lock:
        if _model is None:
            from fastembed import TextEmbedding  # 무거워서 쓸 때만 불러옴
            # mmap: 단어 벡터 표(0.5GB)를 메모리에 다 올리지 않고 질문에 나온 단어 줄만 디스크에서 읽음
            _model = TextEmbedding(model_name=MODEL, cache_dir=str(MODEL_DIR), mmap=True)
    return _model


def embed(texts):
    with _lock:  # 평가 때 여러 질문이 동시에 들어와도 한 번에 하나씩
        return [v.tolist() for v in embedder().embed(texts)]


def load_chunks():
    """문서를 ## 소제목 단위로 자름 → [{"id": "metrics#순가입", "doc", "title", "text"}]"""
    chunks = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        doc = lines[0].lstrip("# ").strip()
        title, body = None, []
        for line in lines[1:] + ["## "]:
            if line.startswith("## "):
                if title:
                    chunks.append({"id": f"{path.stem}#{title}", "doc": doc, "title": title,
                                   "text": "\n".join(body).strip()})
                title, body = line[3:].strip(), []
            else:
                body.append(line)
    return chunks


# ---------- 키워드 검색 (BM25) ----------

def tokens(text):
    """영문·숫자는 단어 그대로, 한글은 두 글자씩 (형태소 분석기 없이 '응대율' ↔ '응대' 를 맞추기 위함)"""
    out = []
    for w in re.findall(r"[0-9A-Za-z]+|[가-힣]+", text):
        if re.match(r"[가-힣]", w) and len(w) > 1:
            out += [w[i:i + 2] for i in range(len(w) - 1)]
        else:
            out.append(w.lower())
    return out


class BM25:
    def __init__(self, docs, k1=1.2, b=0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.avg = sum(map(len, docs)) / len(docs)
        self.df = {}
        for d in docs:
            for t in set(d):
                self.df[t] = self.df.get(t, 0) + 1

    def scores(self, query):
        n, out = len(self.docs), []
        for d in self.docs:
            s = 0.0
            for t in set(tokens(query)):
                if t in self.df:
                    f = d.count(t)
                    idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                    s += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avg))
            out.append(s)
        return out


def keyword_index():
    global _chunks, _bm25
    with _lock:
        if _bm25 is None:
            _chunks = load_chunks()
            # 소제목(용어)을 두 번 넣어 본문보다 무겁게 셈
            _bm25 = BM25([tokens(f"{c['title']} {c['title']} {c['text']}") for c in _chunks])
    return _chunks, _bm25


# ---------- 벡터 색인 ----------

def build():
    chunks = load_chunks()
    vecs = embed([f"{c['title']}: {c['text']}" for c in chunks])
    INDEX.unlink(missing_ok=True)
    con = duckdb.connect(str(INDEX))
    con.execute(f"CREATE TABLE chunks (id VARCHAR, vec FLOAT[{DIM}])")
    con.executemany("INSERT INTO chunks VALUES (?, ?)", [[c["id"], v] for c, v in zip(chunks, vecs)])
    con.close()
    return len(chunks)


def vector_scores(question):
    """조각 id → 코사인 유사도 (DuckDB 배열 함수로 계산)"""
    global _con
    with _lock:
        if _con is None:
            if not INDEX.exists():
                build()
            _con = duckdb.connect(str(INDEX), read_only=True)
    qvec = embed([question])[0]
    rows = _con.cursor().execute(
        f"SELECT id, array_cosine_similarity(vec, ?::FLOAT[{DIM}]) FROM chunks", [qvec]).fetchall()
    return dict(rows)


def search(question, k=TOP_K, mode=None, min_score=None):
    """질문과 가까운 문서 조각 k개. mode: hybrid / bm25 / vector (기본은 RAG_MODE)"""
    mode = mode or MODE
    min_score = MIN_SCORE[mode] if min_score is None else min_score
    chunks, bm25 = keyword_index()
    compact = question.replace(" ", "")
    kw = [b + (TERM_BONUS if c["title"].replace(" ", "") in compact else 0)
          for c, b in zip(chunks, bm25.scores(question))]
    cos = vector_scores(question) if mode != "bm25" else {}
    hits = []
    for c, b in zip(chunks, kw):
        score = {"hybrid": cos.get(c["id"], 0) + BM25_WEIGHT * b, "vector": cos.get(c["id"], 0), "bm25": b}[mode]
        hits.append({**c, "score": round(score, 3), "term": c["title"].replace(" ", "") in compact})
    hits.sort(key=lambda h: h["score"], reverse=True)
    return [h for h in hits[:k] if h["score"] >= min_score]


def to_prompt(hits):
    return "\n\n".join(f"### {h['title']} ({h['doc']})\n{h['text']}" for h in hits)


def evaluate(mode, min_score=None):
    """지식 문항·바꿔 말한 질문: 정답 조각이 검색되나 / 기본 40문항: 관계없는 조각이 몇 개 붙나"""
    from questions import QUESTIONS
    from questions_knowledge import KNOWLEDGE_QUESTIONS, PARAPHRASES

    def recall(qs):
        hit = top1 = 0
        misses = []
        for q in qs:
            ids = [h["id"] for h in search(q["question"], mode=mode, min_score=min_score)]
            ok = set(q["docs"]) <= set(ids)
            hit += ok
            top1 += bool(ids) and ids[0] in q["docs"]
            if not ok:
                misses.append((q["question"], q["docs"], ids))
        return hit, top1, misses

    k_hit, k_top1, k_miss = recall(KNOWLEDGE_QUESTIONS)
    p_hit, _, p_miss = recall(PARAPHRASES)
    noise = sum(len(search(q["question"], mode=mode, min_score=min_score)) for q in QUESTIONS) / len(QUESTIONS)
    return {"knowledge": (k_hit, len(KNOWLEDGE_QUESTIONS)), "top1": k_top1,
            "paraphrase": (p_hit, len(PARAPHRASES)), "base_chunks": noise, "misses": k_miss + p_miss}


if __name__ == "__main__":
    if "--build" in sys.argv:
        print(f"조각 {build()}개 색인 → {INDEX}")
    elif "--eval" in sys.argv:
        # CI에서는 --mode bm25 로 모델 없이 점검, 로컬에서는 세 방식 모두 비교
        modes = [sys.argv[sys.argv.index("--mode") + 1]] if "--mode" in sys.argv else ["vector", "bm25", "hybrid"]
        print(f"| 방식 | 지식 문항 Recall@{TOP_K} | 1순위 적중 | 바꿔 말한 질문 | 기본 문항에 붙는 조각 |")
        print("|---|---|---|---|---|")
        failed = False
        for mode in modes:
            r = evaluate(mode)
            print(f"| {mode} (기준 {MIN_SCORE[mode]}) | {r['knowledge'][0]}/{r['knowledge'][1]} | "
                  f"{r['top1']}/{r['knowledge'][1]} | {r['paraphrase'][0]}/{r['paraphrase'][1]} | {r['base_chunks']:.2f}개 |")
            for m in r["misses"]:
                print("  놓침:", m)
            if mode != "vector":  # 실제로 쓰는 방식은 사내 용어 문항을 전부 찾아야 함
                failed |= r["knowledge"][0] < r["knowledge"][1]
        if failed:
            raise SystemExit(1)  # CI가 빨간불: 문서나 설정을 바꿨더니 검색이 나빠짐
    else:
        for h in search(" ".join(sys.argv[1:]) or "골든타임 응대율 알려줘", min_score=-1):
            print(f"{h['score']:.3f}  {h['id']}")
