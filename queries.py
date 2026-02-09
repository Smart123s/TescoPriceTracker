FULL_PRODUCT_QUERY = """
query GetProduct($tpnc: String) {
  product(tpnc: $tpnc) {
    id
    title
    defaultImageUrl
    productType
    details {
      packSize {
        value
        units
      }
    }
    price {
      actual
      unitPrice
      unitOfMeasure
    }
    promotions {
      id
      startDate
      endDate
      description
      attributes
      price {
        afterDiscount
      }
    }
  }
}
"""

PRICE_ONLY_QUERY = """
query GetProductPrice($tpnc: String) {
  product(tpnc: $tpnc) {
    id
    price {
      actual
      unitPrice
      unitOfMeasure
    }
    promotions {
      id
      startDate
      endDate
      description
      attributes
      price {
        afterDiscount
      }
    }
  }
}
"""
