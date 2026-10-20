#!/bin/bash
# 20:00 이 되면 재학습을 시작한다. 잠자기로 늦어져도 깨어난 뒤 바로 돈다
# (sleep 으로 세는 대신 **시계를 본다**).
cd /Users/hwangmin/development/pj/min/mut
while :; do
  H=$(date +%H); M=$(date +%M)
  [ "$((10#$H))" -ge 20 ] && break
  sleep 60
done
echo "=== 예약 발동 $(date +'%m-%d %H:%M') ===" 
exec eval/train_tonight.sh
