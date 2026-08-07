/** 租户库存模式（与后端 inventory_settings 对齐） */
export type InventoryCapabilities = {
  shared_pool: boolean
  allocate_ui: boolean
  stock_docs: boolean
  issue_gate: boolean
  warehouse_dim: boolean
}

export type InventoryConfig = {
  model: string
  auto_allocate_on_receive: boolean
  issue_required: boolean
  kit_include_unallocated_pool: boolean
  cost_basis: 'po_received' | 'issued' | string
  cutover_phase?: string
  cutover_at?: string | null
  capabilities: InventoryCapabilities
}

export const DEFAULT_INVENTORY: InventoryConfig = {
  model: 'pool_allocate',
  auto_allocate_on_receive: true,
  issue_required: false,
  kit_include_unallocated_pool: false,
  cost_basis: 'po_received',
  cutover_phase: 'pool_allocate_live',
  cutover_at: null,
  capabilities: {
    shared_pool: true,
    allocate_ui: false,
    stock_docs: true,
    issue_gate: false,
    warehouse_dim: false,
  },
}

export type InventoryCapabilityCode = keyof InventoryCapabilities

export function normalizeInventory(raw: unknown): InventoryConfig {
  const d = DEFAULT_INVENTORY
  if (!raw || typeof raw !== 'object') return { ...d, capabilities: { ...d.capabilities } }
  const o = raw as Record<string, unknown>
  const capsIn = (o.capabilities && typeof o.capabilities === 'object' ? o.capabilities : {}) as Record<
    string,
    unknown
  >
  return {
    model: typeof o.model === 'string' ? o.model : d.model,
    auto_allocate_on_receive:
      typeof o.auto_allocate_on_receive === 'boolean' ? o.auto_allocate_on_receive : d.auto_allocate_on_receive,
    issue_required: typeof o.issue_required === 'boolean' ? o.issue_required : d.issue_required,
    kit_include_unallocated_pool:
      typeof o.kit_include_unallocated_pool === 'boolean'
        ? o.kit_include_unallocated_pool
        : d.kit_include_unallocated_pool,
    cost_basis: typeof o.cost_basis === 'string' ? o.cost_basis : d.cost_basis,
    cutover_phase: typeof o.cutover_phase === 'string' ? o.cutover_phase : d.cutover_phase,
    cutover_at: (o.cutover_at as string | null | undefined) ?? d.cutover_at,
    capabilities: {
      shared_pool: capsIn.shared_pool !== false,
      allocate_ui: !!capsIn.allocate_ui,
      stock_docs: capsIn.stock_docs !== false,
      issue_gate: !!capsIn.issue_gate,
      warehouse_dim: !!capsIn.warehouse_dim,
    },
  }
}
