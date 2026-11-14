function task_callback(tsk, state)
	local tm = get_task_manager()
	local id = tsk:get_id()
	
	local rtask = tm.task_info[id]
	if not (rtask) then
		return 
	end 
	
	local giver_npc_id = rtask.task_giver_id -- mlr
	
	--printf("task_callback %s state=%s",id,state == task.fail and "fail" or state == task.completed and "complete" or state)
	if (state == task.fail) then
		news_manager.send_task(db.actor, "fail", tsk)
		
		rtask.status = "fail"
		
		if (rtask.cancelled_by_actor) then
			game_statistics.increment_statistic("tasks_cancelled")
			if (rtask.on_cancel) then
				xr_logic.pick_section_from_condlist(db.actor, db.actor, rtask.on_cancel)
				save_var(db.actor,id,nil) -- Tronex: reset saved data
			end

		else
			game_statistics.increment_statistic("tasks_failed")
			if (rtask.on_fail) then
				xr_logic.pick_section_from_condlist(db.actor, db.actor, rtask.on_fail)
				save_var(db.actor,id,nil) -- Tronex: reset saved data
			end
		end
		
		if (rtask.repeat_timeout) then
			rtask.cancelled_by_actor = nil
			rtask.forced_status = nil
			rtask.t = nil
			rtask.timeout = game.get_game_time()
			rtask.stage = 255
		else
			tm.task_info[id] = nil
		end
	elseif (state == task.completed) then 
		if (rtask.on_complete) then
			xr_logic.pick_section_from_condlist(db.actor, db.actor, rtask.on_complete)
			save_var(db.actor,id,nil) -- Tronex: reset saved data
		end
		rtask:give_reward()
		rtask.status = "completed"
		game_statistics.increment_statistic("tasks_completed")
		
		-- Toolkits reward progress
		local cnt = load_var(db.actor, "toolkit_reward_count") or 0
		save_var(db.actor, "toolkit_reward_count", cnt + 1)
		--printf("task_manager | toolkit_reward_count: %s", cnt + 1)
		
		if (rtask.repeat_timeout) then
			rtask.cancelled_by_actor = nil
			rtask.forced_status = nil
			rtask.t = nil
			rtask.timeout = game.get_game_time()
			rtask.stage = 255
		else 
			tm.task_info[id] = nil
		end
	end
end

