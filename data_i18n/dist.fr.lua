--Script de distillation répartie sur trois récipients.
--La distillation commence par le récipient 0. On mémorise la température du bouilleur au début de l’ébullition.
--Quand la T du bouilleur monte de la valeur réglée, on bascule le servomoteur sur la position donnée.

--RÉGLAGES INITIAUX
t_delta1 = 4 --première consigne de température du bouilleur, une fois dépassée le récipient change
t_delta2 = 4 --deuxième consigne de température du bouilleur, une fois dépassée le récipient change
power_delta = 10 -- de ce pourcentage la puissance actuelle baissera, si 0 - on ne baisse pas
use_temp = 0 --si 1 - passage au récipient suivant selon la température, si 0 - selon le degré

-- DÉFINITION DES VARIABLES
b_temp = getNumVariable("boil_temp") + 0 --on récupère la température d’ébullition mémorisée
alcohol = getNumVariable("alcohol") + 0 --on récupère le degré actuel, calculé d’après la température du bouilleur
alcohol_s = getNumVariable("alcohol_s") + 0 --on récupère le degré au moment où le bouilleur s’est mis à bouillir
TankTemp = getNumVariable("TankTemp") + 0 --on récupère la T actuelle du bouilleur
PowerOn = getNumVariable("PowerOn") + 0 --on récupère l’état de l’alimentation en puissance
target_power_volt = getNumVariable("target_power_volt") + 0 --on récupère la puissance actuelle
capacity_num = getNumVariable("capacity_num") + 0 --on récupère le récipient actuel
sg = getObject("sg", "NUMERIC") + 0 -- on récupère l’état de démarrage du script
gb = getObject("gb", "NUMERIC") + 0 -- on récupère l’état de la réaction au début de l’ébullition
alcohol_invalid = getObject("alcohol_invalid", "NUMERIC") + 0 -- on récupère l’état de degré indisponible

local function changeCapacity(num)
  setCapacity(num) --on définit le récipient №num
  sendMsg("Récipient défini "..num.."!", -1) --on écrit dans la console du navigateur
  sendMsg("Récipient défini "..num.."!", 2) --on écrit à l’opérateur
end

-- le script a démarré
if (sg == 0) then
  setObject("sg", 1)
  changeCapacity(0)
  setPower(1)
  setLuaStatus("Distillation selon Gabriel démarrée")
  sendMsg("Distillation selon Gabriel démarrée!", 2) --on écrit à l’opérateur
end

-- le script a réagi au début de l’ébullition
if (gb == 0 and b_temp > 0) then
  setObject("gb", 1)
  sendMsg("Soutirage vers le récipient démarré №0!", 2) --on écrit à l’opérateur
  --l’ébullition a commencé - on baisse la puissance de power_delta pourcents
  if (PowerOn + 0 == 1 and target_power_volt == 0) then
    --si mode de montée en chauffe, où la tension actuelle est inconnue
    target_power_volt = 220
  end
  --si power_delta > 0 on change la tension cible
  if (power_delta > 0) then
    target_power_volt = target_power_volt - target_power_volt/100*power_delta
    setCurrentPower(target_power_volt)
  end
end

--Traitement de la logique de changement de récipient
if b_temp > 0 then
setLuaStatus(string.format("Degré actuel = %.2f ; T de début d’ébullition = %.2f", alcohol, b_temp))
  if (use_temp == 1) then
  --logique par température
    if ((capacity_num + 0 == 0) and ((b_temp + t_delta1) <= TankTemp)) then
      changeCapacity(1)
    elseif ((capacity_num + 0 == 1) and ((b_temp + t_delta1 + t_delta2) <= TankTemp)) then
      changeCapacity(2)
    end
  else
  --logique par degré
    if alcohol >= 0 and alcohol_s >= 0 then
      setObject("alcohol_invalid", 0)
      if (capacity_num + 0 == 0) and (alcohol <= alcohol_s / 2) then
        --il reste la moitié de l’alcool - on passe au récipient 1
        changeCapacity(1)
      elseif (capacity_num + 0 == 1) and (alcohol <= alcohol_s / 4) then
        --il reste un quart de l’alcool - on passe au récipient 2
        changeCapacity(2)
      end
    elseif alcohol_invalid == 0 then
      setObject("alcohol_invalid", 1)
      sendMsg("Degré indisponible : changement de récipient reporté", 1)
    end
  end
end
