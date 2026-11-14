task_status_functor.assault_task_status_functor = function (tsk,task_id)
	if not (db.actor and tsk) then return end

	if (tsk.stage == 1) then  return end -- already completed
	
	local var = load_var(db.actor, task_id) -- check saved data
	if (not var) then return "fail" end
	
	local smart_id = var.smart_id -- check smart id
	if (not smart_id) then return "fail" end
	
	local smrt = SIMBOARD.smarts[smart_id] -- check smart object (special defines)
	if (not smrt) then return "fail" end

	local smart = smrt.smrt -- check smart server object
	if (not smart) then return "fail" end
	
	-- in case sim_avail is set true during the player's tsk. with simulation_objects.available_by_id[smart.id] nil means unprocess, false is absolutely not avail
	if (simulation_objects.available_by_id[smart.id] == nil) then 
		return
	elseif (simulation_objects.available_by_id[smart.id] == false) then
		printe("! %s | task failed because smart no longer available", task_id)
		return "fail"
	end
	
	
	-- Store factions parameters for the first time to re-use it
	if (not cache_assault_func[task_id]) then
		cache_assault_func[task_id] = {}
		local params = parse_list(task_manager.task_ini,task_id,"status_functor_params")
		if var.is_enemy then
			for i=1,#params do
				if is_squad_monster[params[i]] or factions_list[params[i]] then
					cache_assault_func[task_id][i] = params[i]
					printf("/ %s | Faction [%s] is re-added to cache_assault_func table", task_id, params[i])
				end
			end
		elseif (not is_squad_monster[params[1]]) then
			for fac,_ in pairs(factions_list) do
				local cnt = 0
				local is_enemy_to_actor = true --game_relations.is_factions_enemies(fac, get_actor_true_community())
				for i=1,#params do
					if (fac ~= params[i]) and is_enemy_to_actor and game_relations.is_factions_enemies(fac, params[i]) then
						cnt = cnt + 1
					end
				end
				if (cnt == #params) then
					local idx = #cache_assault_func[task_id] + 1
					cache_assault_func[task_id][idx] = fac
					printf("/ %s | Faction [%s] is re-added to cache_assault_func table", task_id, fac)
				end
			end
		end
		if (#cache_assault_func[task_id] == 0) then
			printe("! %s | no enemy factions found",task_id)
			return "fail"
		end
	end
	
	
	-- Timer for less pressure
	local tg = time_global()
	if (tsk.__check_smart_time and tg < tsk.__check_smart_time) then
		return
	end
	tsk.__check_smart_time = tg+3000
	
	-- cleaning data for re-assign next
	local squad_id = var.squad_id
	var.squad_id = nil
	save_var(db.actor, task_id, var)
	
	-- Scan saved squad
	local squad = squad_id and alife_object(squad_id)
	if squad then
		local pass_this = evaluate_squads_smarts(task_id, var, squad, smart)
		if pass_this then
			return
		end
	end
	
	-- Scan all squads
	for id,v in pairs( SIMBOARD.squads ) do
		local squad = alife_object(id)
		if squad then
			local pass_this = evaluate_squads_smarts(task_id, var, squad, smart)
			if pass_this then
				return
			end
		end
	end
	
	-- If smart is controllable by factions, player dominate it
	if (smart.faction_controlled) then
		local comm = character_community(db.actor):sub(7)
		smart.faction = factions_list[comm] and comm or smart.faction
	end
	
	-- Assuming no squads means that target smart got cleared
	tsk.stage = 1
end


