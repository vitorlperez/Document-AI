#!/usr/bin/env zsh
cd "${0:A:h}"
: > results/chain3.log
for step in "bench_ann.py --label 10k" "bench_ann.py --label 50k" "bench_filter.py --label 10k --warm --runs 4" "bench_filter.py --label 50k --warm --runs 3"; do
  name=${${step// /_}//--/}
  ./run.sh ${=step} 2>&1 | cut -c1-300 | grep -v '"event"' > results/${name}.log
  echo "$step exit=${pipestatus[1]} $(date +%T)" >> results/chain3.log
done
echo ALLDONE >> results/chain3.log
