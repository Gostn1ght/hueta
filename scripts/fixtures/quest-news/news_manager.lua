local action_descr_by_type = {
	new = "general_new_task",
	complete = "general_complete_task",
	fail = "general_fail_task",
	reversed = "general_reverse_task",
	updated = "general_update_task"
}

local showcase_item_icon = {
	["in"] = "ui_inGame2_Predmet_poluchen",
	["out"] = "ui_inGame2_Predmet_otdan",
	["docs"] = "ui_inGame2_Poslednie_razrabotki",
}

local showcase_item_caption = {
	["in"] = "general_in_item",
	["out"] = "general_out_item",
}

local showcase_money_icon = {
	["in"] = "ui_inGame2_Dengi_polucheni",
	["out"] = "ui_inGame2_Dengi_otdani",
}

local showcase_money_caption = {
	["in"] = "general_in_money",
	["out"] = "general_out_money",
}

function send_task(actor, type, tsk)
	if db.actor == nil then
		return false
	end
	local time_on_screen = (type == "updated") and 5000 or 10000
	xr_sound.set_sound_play(AC_ID, "pda_task")
	local news_caption = game.translate_string(action_descr_by_type[type])
	local news_text = game.translate_string(tsk:get_title() or "")
	local icon = tsk:get_icon_name()
	if(icon==nil) then
		icon = "ui_iconsTotal_storyline"
	end

	if db.actor:is_talking() then
		db.actor:give_talk_message2(news_caption, news_text..".", icon, "iconed_answer_item")
	else
		db.actor:give_game_news(news_caption, news_text..".", icon, 0, time_on_screen)
	end

end

function relocate_money(actor, type, amount)
	if db.actor == nil then return false end
	
	local news_text = game.translate_string(tostring(amount))
	local news_caption = showcase_money_caption[type] and game.translate_string(showcase_money_caption[type]) or ""
	local news_ico = showcase_money_icon[type] or "ui_inGame2_Dengi_polucheni"
	
	if db.actor:is_talking() then
		db.actor:give_talk_message2(news_caption, news_text, news_ico, "iconed_answer_item")
	else
		db.actor:give_game_news(news_caption, news_text, news_ico, 0, 3000)
	end
end

function relocate_item(actor, type, item, amount)
	if db.actor == nil then return false end
	if not (item and ini_sys:section_exist(item)) then 
		printe("!ERROR: relocate_item - section %s does not exist",item)
		return false
	end

	amount = amount or 1
	local news_text = item and ui_item.get_sec_name(item) or ""
	local news_caption = showcase_item_caption[type] and game.translate_string(showcase_item_caption[type]) or ""
	local news_ico = showcase_item_icon[type] or "ui_inGame2_Predmet_poluchen"
	if (amount > 1) then
		news_text = news_text .. " x" .. amount
	end
	
	if db.actor:is_talking() then
		db.actor:give_talk_message2(news_caption, news_text, news_ico, "iconed_answer_item")
	else
		db.actor:give_game_news(news_caption, news_text, news_ico, 0, 3000)
	end
end
