function CGeneralTask:give_reward()
	local money = self.reward_money and xr_logic.pick_section_from_condlist(db.actor, db.actor, self.reward_money)
	local items = self.reward_item and xr_logic.pick_section_from_condlist(db.actor, db.actor, self.reward_item)

	-- Награду можно выдать двумя методами: от нпс или просто свалитьс неба. Если не найден НПС, с которым мы в диалоге, то просто валим с неба

	local npc = get_speaker()
	if not (npc) then
		return 
	end

	if money ~= nil then
		dialogs.relocate_money(npc, tonumber(money), "in")
	end

	if items ~= nil then
		local ancillary_item_table = {}
		for k,v in pairs(parse_names(items)) do
			if ancillary_item_table[v] == nil then
				ancillary_item_table[v] = 1
			else
				ancillary_item_table[v] = ancillary_item_table[v] + 1
			end
		end
		for k,v in pairs(ancillary_item_table) do
			dialogs.relocate_item_section(npc, k, "in", v)
		end
	end
end
