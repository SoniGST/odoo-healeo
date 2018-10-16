# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
import random

from odoo import models, fields, api
from odoo.addons.component.core import Component
from odoo.addons.queue_job.exception import RetryableJobError
from odoo.addons.queue_job.job import job

_logger = logging.getLogger(__name__)


def chunks(items, length):
    for index in xrange(0, len(items), length):
        yield items[index:index + length]


class AmazonProductProduct(models.Model):
    _name = 'amazon.product.product'
    _inherit = 'amazon.binding'
    _inherits = {'product.product':'odoo_id'}
    _description = 'Amazon Product'

    odoo_id = fields.Many2one(comodel_name='product.product',
                              string='Product',
                              required=True,
                              ondelete='restrict')

    asin = fields.Char('ASIN', readonly=True)
    id_type_product = fields.Selection(selection=[('GCID', 'GCID'),
                                                  ('UPC', 'UPC'),
                                                  ('EAN', 'EAN'),
                                                  ('ISBN', 'ISBN'),
                                                  ('JAN', 'JAN')],
                                       string='Type product Id')

    id_product = fields.Char()
    status = fields.Char('status', required=False)
    sku = fields.Char('SKU', required=True, readonly=True)
    brand = fields.Char('Brand')
    created_at = fields.Date('Created At (on Amazon)')
    updated_at = fields.Date('Updated At (on Amazon)')
    amazon_qty = fields.Float(string='Computed Quantity',
                              help="Last computed quantity to send "
                                   "on Amazon.")

    product_product_market_ids = fields.One2many('amazon.product.product.detail', 'product_id',
                                                 string='Product data on marketplaces', copy=True)
    height = fields.Float('Height', default=0)
    length = fields.Float('Length', default=0)
    weight = fields.Float('Weight', default=0)
    width = fields.Float('Width', default=0)

    # Min and max margin stablished for the calculation of the price on product and product price details if these do not be informed
    # If these fields do not be informed, gets the margin limits of backend
    change_prices = fields.Boolean('Change the prices', default=True)
    min_margin = fields.Float('Minimal margin', default=None)
    max_margin = fields.Float('Minimal margin', default=None)

    RECOMPUTE_QTY_STEP = 1000  # products at a time

    @job(default_channel='root.amazon')
    @api.model
    def import_record(self, backend, external_id):
        _super = super(AmazonProductProduct, self)
        try:
            result = _super.import_record(backend, external_id)
            if not result:
                raise RetryableJobError(msg='The product of the backend %s hasn\'t could not be imported. \n %s' % (backend.name, external_id),
                                        seconds=random.randint(90, 600))
        except Exception as e:
            if e.message.find('current transaction is aborted') > -1 or e.message.find('could not serialize access due to concurrent update') > -1:
                raise RetryableJobError('A concurrent job is already exporting the same record '
                                        '(%s). The job will be retried later.' % self.model._name, random.randint(60, 300), True)
            raise e

    @job(default_channel='root.amazon')
    @api.model
    def export_batch(self, backend):
        '''
        We will use this method to get the products, get their prices and their stocks and export this on Amazon
        :param backend:
        :return:
        '''

        if backend.sync_stock:
            export_prod = []
            products = self.env['amazon.product.product'].search([('backend_id', '=', backend.id)])

            with backend.work_on(self._name) as work:
                exporter_stock = work.component(usage='amazon.product.stock.exporter')
                i = [detail for product in products for detail in product.product_product_market_ids if product.product_product_market_ids]
                for detail in i:
                    virtual_available = detail.product_id.odoo_id._compute_check_stock()
                    export_prod.append({'sku':detail.sku, 'Quantity':0 if virtual_available<0 else virtual_available, 'id_mws':detail.marketplace_id.id_mws})

                exporter_stock.run(export_prod)


        if backend.change_prices and backend.min_margin and backend.max_margin:
            export_prices = []
            # TODO Get products that have stock to sell
            products = self.env['amazon.product.product'].search([('backend_id', '=', backend.id)])

            # TODO Get lowest prices and buybox of the products

            # TODO Calc the price for the product, we need to have in mind the next tips
            #   1. If we have the buybox we don't anything
            #   2. if the lowest price is mine and the buybox is not mine, we need reduce the price
            #   3.
            with backend.work_on(self._name) as work:
                exporter_stock = work.component(usage='product.price.exporter')
                i = [detail for product in products for detail in product.product_product_market_ids if
                     product.product_product_market_ids]
                for detail in i:
                    virtual_available = detail.product_id.odoo_id._compute_check_stock()
                    export_prod.append(
                        {'sku': detail.sku, 'Quantity': 0 if virtual_available < 0 else virtual_available,
                         'id_mws': detail.marketplace_id.id_mws})

                exporter_stock.run(export_prod)
        return


class ProductProductDetail(models.Model):
    _name = 'amazon.product.product.detail'
    _inherits = {'product.pricelist':'odoo_id'}
    _description = 'Amazon Product Variant on Every Marketplace'

    odoo_id = fields.Many2one(comodel_name='product.pricelist',
                              string='PriceList',
                              required=True,
                              ondelete='restrict')

    product_id = fields.Many2one('amazon.product.product', 'product_data_market_ids', ondelete='cascade', required=True,
                                 readonly=True)
    title = fields.Char('Product_name', required=False)
    price = fields.Float('Price', required=False)  # This price have the tax included
    min_allowed_price = fields.Float('Min allowed price', required=False)  # This is the min price allowed
    max_allowed_price = fields.Float('Max allowed price', required=False)  # This is the max price allowed
    currency_price = fields.Many2one('res.currency', 'Currency price', required=False)
    price_ship = fields.Float('Price of ship', required=False)  # This price have the tax included
    currency_ship_price = fields.Many2one('res.currency', 'Currency price ship', required=False)
    marketplace_id = fields.Many2one('amazon.config.marketplace', "marketplace_id")
    status = fields.Selection(selection=[('Active', 'Active'),
                                         ('Inactive', 'Inactive'),
                                         ('Unpublished', 'Unpublished'),
                                         ('Submmited', 'Submmited')],
                              string='Status', default='Active')
    stock = fields.Integer('Stock')
    date_created = fields.Datetime('date_created', required=False)
    category_id = fields.Many2one('amazon.config.product.category', 'Category',
                                  default=lambda self:self.env['amazon.config.product.category'].search(
                                      [('name', '=', 'default')]))
    has_buybox = fields.Boolean(string='Is the buybox winner', default=False)
    has_lowest_price = fields.Boolean(string='Is the lowest price', default=False)
    lowest_price = fields.Float('Lowest total price')
    lowest_product_price = fields.Float('Lowest product price', required=False)
    lowest_shipping_price = fields.Float('Lower shipping price', required=False)
    merchant_shipping_group = fields.Char('Shipping template name')

    # Min and max margin stablished for the calculation of the price on product and product price details if these do not be informed
    change_prices = fields.Boolean('Change the prices', default=True)
    min_margin = fields.Float('Minimal margin', default=None)
    max_margin = fields.Float('Minimal margin', default=None)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    amazon_bind_ids = fields.One2many(
        comodel_name='amazon.product.product',
        inverse_name='odoo_id',
        string='Amazon Bindings',
    )

    @api.depends('qty_available', 'virtual_available', 'stock_quant_ids', 'stock_move_ids', 'outgoing_qty',
                 'product_uom_qty', 'product_uom', 'route_id')
    def _compute_check_stock(self):
        qty_total_product = 0
        # Add the virtual avaiable of the product itself
        if self.virtual_available and self.virtual_available > 0:
            qty_total_product = self.virtual_available
        # Add the calc of the stock avaiable counting with the BoM stock
        if self.bom_ids:

            # if we have bom, we need to calculate the forecast stock
            qty_bom_produced = None
            for bom in self.bom_ids:

                for line_bom in bom.bom_line_ids:
                    # We are going to divide the product bom stock for quantity of bom
                    aux = int(line_bom.product_id.virtual_available / line_bom.product_qty)
                    # If is the first ocurrence or the calc of stock avaiable with this product is lower than we are saved, we udpated this field
                    if qty_bom_produced == None or aux < qty_bom_produced:
                        qty_bom_produced = aux

            qty_total_product += qty_bom_produced if qty_bom_produced else 0

        return qty_total_product


class ProductPriceList(models.Model):
    _inherit = 'product.pricelist'

    amazon_bind_ids = fields.One2many(
        comodel_name='amazon.product.product.detail',
        inverse_name='odoo_id',
        string='Amazon Bindings',
    )

    sku = fields.Char('Product reference on Amazon')

    marketplace_price_id = fields.Many2one('amazon.config.marketplace', "marketplace_id")


class AmazonProductUoM(models.Model):
    _name = 'amazon.product.uom'

    product_uom_id = fields.Many2one('product.uom', 'Product UoM')
    name = fields.Char()

class AmazonHistoricProductPrice(models.Model):
    _name ='amazon.historic.product.price'

    product_detail = fields.Many2one('amazon.product.product.detail')
    change_date = fields.Datetime('Time when my price change')
    type_change = fields.Selection(selection=[('UP', 'UP'),
                                              ('DOWN', 'DOWN'),
                                              ('EQUAL', 'EQUAL'),])

    before_price = fields.Float('Price before change')
    after_price = fields.Float('Price after change')
    competitor_price = fields.Float('Competitor price')
    buybox_mine = fields.Boolean('Is the buybox mine when the price is changed')


class ProductProductAdapter(Component):
    _name = 'amazon.product.product.adapter'
    _inherit = 'amazon.adapter'
    _apply_on = 'amazon.product.product'

    def _call(self, method, arguments):
        try:
            return super(ProductProductAdapter, self)._call(method, arguments)
        except Exception:
            raise

    def get_lowest_price(self, arguments):
        try:
            assert arguments
            return self._call(method='get_lowest_price_and_buybox', arguments=arguments)
        except AssertionError:
            _logger.error('There aren\'t (%s) parameters for %s', 'get_lowest_price')
            raise

    def get_my_price(self, arguments):
        try:
            assert arguments
            return self._call(method='get_my_price_product', arguments=arguments)
        except AssertionError:
            _logger.error('There aren\'t (%s) parameters for %s', 'get_my_price')
            raise

    def get_category(self, arguments):
        try:
            assert arguments
            return self._call(method='get_category_product', arguments=arguments)
        except AssertionError:
            _logger.error('There aren\'t (%s) parameters for %s', 'get_category_product')
            raise
