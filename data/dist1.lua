target_temp = 94 --температура, с которой начнется укрепление при дистилляции - откроется клапан воды для охлаждения.

if (PowerOn == 1 and valve_status == 1 and TankTemp < target_temp) then
  openValve(0)
else if (PowerOn == 1 and valve_status == 0 and TankTemp >= target_temp) then
  openValve(1)
end