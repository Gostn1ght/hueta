task_status_functor.bounty_task = function(tsk,task_id)
	if not (axr_task_manager.is_task_giver_valid(tsk)) then
		return "fail"
	end

	if (tsk.stage == 0) then
		local id = axr_task_manager.bounties_by_id[task_id]
		if not (id) then
			return "fail"
		end
		local se_obj = id and alife_object(id)
		if not (se_obj) then
			return "fail"
		end
		if not (IsStalker(nil,se_obj:clsid())) then
			return "fail"
		end
		if not (se_obj:alive()) then
			tsk.stage = 1
		end
	elseif (tsk.stage == 254) then
		return "fail"
	end
end
