task_status_functor.delivery_task = function(tsk,task_id)
	if (not db.actor) or (not tsk) then
		return
	end
	
	local var = load_var(db.actor, task_id)
	if (not var) then return end
	local stage = tsk.stage
	
	-- Give quest item upon accepting the quest
	if (not has_alife_info(task_id .. "_quest_item_received")) and (var.item_1_sec) then
		local se_item_1 = alife_create_item(var.item_1_sec, db.actor)
		if not (se_item_1 and se_item_1.id) then return end
		
		printdbg("- %s | quest_item_received: %s",task_id, var.item_1_sec)
		local t = var
		t.item_1_id = se_item_1.id
		save_var(db.actor, task_id, t)
		
		db.actor:give_info_portion(task_id .. "_quest_item_received")
		news_manager.relocate_item(db.actor, "in", var.item_1_sec, 1)
		return
	end
	
	local item_1_obj = var.item_1_id and alife_object(var.item_1_id)
	
	local se_target = var.target_id and alife_object(var.target_id) -- server object
	local target = se_target and db.storage[se_target.id] and db.storage[se_target.id].object or nil -- game object
	local is_enemy = false --game_relations.is_factions_enemies(get_actor_true_community(), var.target_comm)
	
	-- if the target has vanished or dead or become an enemy, complete the quest
	if (not se_target) or (target and (not target:alive())) or is_enemy then
		return "fail"
	end
	
	-- Save task giver squad id
	if (not var.target_squad_id) then
		local target_squad = se_target and se_target.group_id and se_target.group_id ~= 65535 and alife_object(se_target.group_id)
		if target_squad then
			sim_offline_combat.task_squads[target_squad.id] = true
			var.target_squad_id = target_squad.id
			save_var(db.actor, task_id, var)
			
			-- Reset stay time once
			if (not target_squad:get_script_target()) and (target_squad.current_action == 1) then
				target_squad.stay_time = game.get_game_time() 
			end
		end
	end
	

	-- stage: 0
	-- status: player accepted the quest
	-- objective: take the quest item
	-- marker: quest item
	if stage == 0 then
		-- if actor retrieved item 1
		if utils_item.has_item_by_id(nil, var.item_1_id , var.item_1_sec) then
			tsk.stage = 1
			
		-- if item 1 vanished, fail the quest
		else 
			if (not item_1_obj) or (item_1_obj and (item_1_obj:section_name() ~= var.item_1_sec)) then
				return "fail"
			end
		end
	end
	
	-- stage: 1
	-- status: player has the quest item
	-- objective: deliver it to the target
	-- marker: target npc
	if stage == 1 then
		-- if actor lost item 1 recently
		if (not utils_item.has_item_by_id(nil, var.item_1_id , var.item_1_sec)) then
			tsk.stage = 0
		end
	end
	
	-- stage: 2 (not used, this quest is completed via dialog)
	-- status: player has delivered the quest item
	if stage == 2 then
		return "complete"
	end
end


