import { authSettingsApi } from '@/api/authSettings'

export type ProductMode = 'builder' | 'code'

export interface ProductAvailability {
  builder: boolean
  code: boolean
}

const fallbackProductAvailability = (): ProductAvailability => ({ builder: true, code: true })

let availability = fallbackProductAvailability()
let availabilityLoad: Promise<ProductAvailability> | null = null

export function enabledProductModes(
  productAvailability: ProductAvailability,
): ProductMode[] {
  return (['builder', 'code'] as const).filter(product => productAvailability[product])
}

export function defaultProductHome(
  productAvailability: ProductAvailability,
): '/' | '/code/apps' {
  return productAvailability.builder ? '/' : '/code/apps'
}

export function productForRoute(route: {
  path?: string
  meta?: Record<string, unknown>
}): ProductMode | undefined {
  const product = route.meta?.product
  return product === 'builder' || product === 'code' ? product : undefined
}

export function redirectForDisabledProduct(
  productAvailability: ProductAvailability,
  product: ProductMode | undefined,
): '/' | '/code/apps' | undefined {
  if (!product || productAvailability[product]) return undefined
  return defaultProductHome(productAvailability)
}

export function loadProductAvailability(): Promise<ProductAvailability> {
  if (!availabilityLoad) {
    availabilityLoad = authSettingsApi.getPublic()
      .then((settings) => {
        availability = {
          builder: settings.products.builder.enabled,
          code: settings.products.code.enabled,
        }
        return availability
      })
      .catch(() => {
        availability = fallbackProductAvailability()
        return availability
      })
  }
  return availabilityLoad
}

export function resetProductAvailability(): void {
  availability = fallbackProductAvailability()
  availabilityLoad = null
}
