#!/usr/bin/env zsh
# sequential benchmark chain (each step logs to results/); safe to re-run
cd "${0:A:h}"
for step in "10k" "50k" "10k --hnsw" "50k --hnsw"; do
  name=${step// /_}
  ./run.sh bench_sql.py --label ${=step} 2>&1 | cut -c1-300 | grep -v '"event"' > results/sql_${name}.log
  echo "$step exit=${pipestatus[1]} $(date +%T)" >> results/chain.log
done
