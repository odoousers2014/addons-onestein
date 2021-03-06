# -*- coding: utf-8 -*-
##############################################################################
#
#    Copyright (C) 2015 ONESTEiN BV (<http://www.onestein.nl>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import logging
from openerp import models, api, _
from psycopg2 import OperationalError

_logger = logging.getLogger(__name__)


class procurement_order(models.Model):
    _inherit = "procurement.order"

    def legacy_message_post(self, cr, uid, ids, thread_id, body):
        """TODO This is a work around. The new API tries to pass the object ids to kwarg thread_id instead of the
        explicit values (i.e. [procurement.id]), this method circumvents that."""
        self.message_post(cr, uid, thread_id, body)
        return True

    @api.model
    def run(self, autocommit=False, sale_ids=None):
        """Override of stock.procurement.run()."""
        cursor = self._cr
        _logger.debug("ONESTEiN procurement_order run")
        procurements = self.search([('state', 'not in', ('running', 'done', 'cancel'))])
        # Override of a super to procurement.procurement.run() (because we want the superclass's superclass):
        for procurement in procurements:
            # we intentionnaly do the browse under the for loop to avoid caching all ids which would be resource greedy
            # and useless as we'll make a refresh later that will invalidate all the cache (and thus the next iteration
            # will fetch all the ids again)
            procurement = self.browse(procurement.id)
            if procurement.state not in ("running", "done"):
                try:
                    if procurement._assign(procurement=procurement):
                        procurement.refresh()
                        res = procurement._run(procurement=procurement)
                        if res:
                            procurement.write({'state': 'running'})
                        else:
                            procurement.write({'state': 'exception'})
                    else:
                        self.legacy_message_post(
                            thread_id=[procurement.id],
                            body=_('No rule matching this procurement')
                        )
                        procurement.write({'state': 'exception'})
                    if autocommit:
                        cursor.commit()
                except OperationalError:
                    if autocommit:
                        cursor.rollback()
                        continue
                    else:
                        raise
        # End of super.
        # after all the procurements are run, check if some created a draft stock move that needs to be confirmed
        # (we do that in batch because it fasts the picking assignation and the picking state computation)
        move_to_confirm_ids = []
        for procurement in procurements:
            if procurement.state == "running" and procurement.rule_id and procurement.rule_id.action == "move":
                move_to_confirm_ids += [m.id for m in procurement.move_ids if m.state == 'draft']
        if move_to_confirm_ids:
            moves_to_confirm = self.env['stock.move'].browse(move_to_confirm_ids)
            moves_to_confirm.action_confirm(sale_ids=sale_ids)
        return True

