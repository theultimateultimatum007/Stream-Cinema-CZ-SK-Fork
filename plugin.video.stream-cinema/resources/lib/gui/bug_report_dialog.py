# -*- coding: utf-8 -*-
from __future__ import print_function, unicode_literals

import xbmcgui
import xbmc

from resources.lib.common.logger import debug

# Stable control IDs matching BugReportDialog.xml
CTRL_CANCEL = 4001
CTRL_BACK = 4002
CTRL_NEXT = 4003
CTRL_SEND = 4004

CTRL_STEP_INDICATOR = 4011

# Step 1 - category list
CTRL_STEP1_GROUP = 4100
CTRL_CATEGORY_LIST = 4101

# Step 2 - context preview
CTRL_STEP2_GROUP = 4200
CTRL_CONTEXT_TEXTBOX = 4201

# Step 3 - description
CTRL_STEP3_GROUP = 4300
CTRL_DESC_TEXTBOX = 4301
CTRL_DESC_EDIT_BTN = 4302
CTRL_VALIDATION_LABEL = 4303

# Step 4 - confirm + checkboxes
CTRL_STEP4_GROUP = 4400
CTRL_PREVIEW_TEXTBOX = 4401
CTRL_CHK_USERNAME = 4402
CTRL_CHK_LOG = 4403

# Kodi action IDs
ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92
ACTION_SELECT_ITEM = 7

# Mapping step number -> group control id
_STEP_GROUPS = {
    1: CTRL_STEP1_GROUP,
    2: CTRL_STEP2_GROUP,
    3: CTRL_STEP3_GROUP,
    4: CTRL_STEP4_GROUP,
}


class BugReportDialog(xbmcgui.WindowXMLDialog):
    """
    Thin WindowXMLDialog for the bug report wizard.
    All business logic lives in BugReportWizard (wizard.py).
    Pattern mirrors resources/lib/gui/skip.py.
    """

    def __init__(self, *args, **kwargs):
        # 'wizard' MUST be removed before calling the base constructor — the
        # real Kodi WindowXMLDialog only accepts the positional skin args and
        # raises TypeError on unknown keywords (skip.py is always positional).
        self.wizard = kwargs.pop('wizard', None)
        xbmcgui.WindowXMLDialog.__init__(self, *args, **kwargs)
        self._cancelled = False

    # ------------------------------------------------------------------
    # WindowXMLDialog callbacks
    # ------------------------------------------------------------------

    def onInit(self):  # type: () -> None
        debug('BugReport: BugReportDialog.onInit step={}'.format(
            self.wizard.step if self.wizard else '?'))
        self._populate_categories()
        self._show_step(1)
        self.setFocus(self.getControl(CTRL_CATEGORY_LIST))

    def onClick(self, control_id):  # type: (int) -> None
        debug('BugReport: BugReportDialog.onClick id={}'.format(control_id))

        if control_id == CTRL_CANCEL:
            self._cancelled = True
            self.close()

        elif control_id == CTRL_BACK:
            if self.wizard.step > 1:
                self.wizard.prev_step()
                self._refresh_step()
            else:
                self._cancelled = True
                self.close()

        elif control_id == CTRL_NEXT:
            self._on_next()

        elif control_id == CTRL_SEND:
            self._on_send()

        elif control_id == CTRL_DESC_EDIT_BTN:
            self._on_edit_description()

        elif control_id == CTRL_CHK_USERNAME:
            chk = self.getControl(CTRL_CHK_USERNAME)
            self.wizard.include_username = chk.isSelected()
            self._update_preview()

        elif control_id == CTRL_CHK_LOG:
            chk = self.getControl(CTRL_CHK_LOG)
            self.wizard.include_log = chk.isSelected()
            self._update_preview()

    def onAction(self, action):  # type: (xbmcgui.Action) -> None
        action_id = action.getId()
        debug('BugReport: BugReportDialog.onAction id={}'.format(action_id))
        if action_id in (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK):
            self._cancelled = True
            self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _populate_categories(self):
        """Fill the category list from wizard.get_categories()."""
        if not self.wizard:
            return
        list_ctrl = self.getControl(CTRL_CATEGORY_LIST)
        list_ctrl.reset()
        for cat_id, label, sublabel in self.wizard.get_categories():
            item = xbmcgui.ListItem(label=label, label2=sublabel)
            item.setProperty('cat_id', cat_id)
            list_ctrl.addItem(item)

    def _show_step(self, step):
        """Show the group for 'step', hide all others; update buttons."""
        for s, gid in _STEP_GROUPS.items():
            grp = self.getControl(gid)
            grp.setVisible(s == step)

        # Step indicator text is set by wizard
        ind = self.getControl(CTRL_STEP_INDICATOR)
        ind.setLabel(self.wizard.get_step_indicator() if self.wizard else '')

        # Back visibility
        back_ctrl = self.getControl(CTRL_BACK)
        back_ctrl.setEnabled(step > 1)

        # Next vs Send
        next_ctrl = self.getControl(CTRL_NEXT)
        send_ctrl = self.getControl(CTRL_SEND)
        is_last = (step == 4)
        next_ctrl.setVisible(not is_last)
        send_ctrl.setVisible(is_last)

        # Default focus per step
        focus_map = {
            1: CTRL_CATEGORY_LIST,
            2: CTRL_NEXT,
            3: CTRL_DESC_EDIT_BTN,
            4: CTRL_SEND,
        }
        self.setFocus(self.getControl(focus_map.get(step, CTRL_NEXT)))

    def _refresh_step(self):
        """Re-populate current step UI from wizard state and show it."""
        step = self.wizard.step

        if step == 2:
            tb = self.getControl(CTRL_CONTEXT_TEXTBOX)
            tb.setText(self.wizard.get_context_preview())

        elif step == 3:
            self._update_desc_display()

        elif step == 4:
            self._update_checkboxes()
            self._update_preview()

        self._show_step(step)

    def _on_next(self):
        """Validate current step and advance."""
        step = self.wizard.step

        if step == 1:
            # Read selected category
            list_ctrl = self.getControl(CTRL_CATEGORY_LIST)
            pos = list_ctrl.getSelectedPosition()
            item = list_ctrl.getListItem(pos)
            cat_id = item.getProperty('cat_id')
            if not cat_id:
                return
            self.wizard.set_category(cat_id)
            self.wizard.next_step()
            self._refresh_step()

        elif step == 2:
            self.wizard.next_step()
            self._refresh_step()

        elif step == 3:
            errors = self.wizard.validate()
            if errors:
                lbl = self.getControl(CTRL_VALIDATION_LABEL)
                lbl.setLabel(errors[0])
                return
            # Clear any previous validation message
            self.getControl(CTRL_VALIDATION_LABEL).setLabel('')
            self.wizard.next_step()
            self._refresh_step()

    def _on_send(self):
        """Trigger wizard.submit() and close."""
        self.wizard.submit()
        self.close()

    def _on_edit_description(self):
        """Open keyboard for description input, update wizard state."""
        from resources.lib.gui.dialog import dinput
        from resources.lib.language import Strings
        heading = Strings.txt(Strings.BUG_REPORT_DESCRIBE)
        current = self.wizard.description or ''
        new_desc = dinput(heading=heading, default=current)
        if new_desc is None:
            return
        self.wizard.description = new_desc
        self._update_desc_display()

    def _update_desc_display(self):
        tb = self.getControl(CTRL_DESC_TEXTBOX)
        tb.setText(self.wizard.description or '')

    def _update_checkboxes(self):
        """Sync checkbox state with wizard."""
        chk_user = self.getControl(CTRL_CHK_USERNAME)
        chk_log = self.getControl(CTRL_CHK_LOG)
        chk_user.setSelected(self.wizard.include_username)
        chk_log.setSelected(self.wizard.include_log)

    def _update_preview(self):
        """Refresh the preview textbox with current wizard state."""
        tb = self.getControl(CTRL_PREVIEW_TEXTBOX)
        tb.setText(self.wizard.build_preview())
