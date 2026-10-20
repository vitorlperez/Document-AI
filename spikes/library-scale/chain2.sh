#!/usr/bin/env zsh
# second benchmark chain: runs after all indexes/seeds exist; sequential, quiet machine
cd "${0:A:h}"
run() { # name, cmd...
  local name=$1; shift
  ./run.sh "$@" 2>&1 | cut -c1-300 | grep -v '"event"' > results/$name.log
  echo "$name exit=${pipestatus[1]} $(date +%T)" >> results/chain2.log
}
: > results/chain2.log
run api_3k_full bench_api.py --label 3k --runs 5
for l in 1k 10k 50k; do run api_${l}_noask bench_api.py --label $l --runs 5 --skip-ask; done
run sql_3k bench_sql.py --label 3k
run sql_10k_hnsw2 bench_sql.py --label 10k --hnsw
run sql_50k_hnsw2 bench_sql.py --label 50k --hnsw
run filter_10k bench_filter.py --label 10k
run filter_50k bench_filter.py --label 50k
echo ALLDONE >> results/chain2.log
