export interface TableColumn {
  title: string
  widthRem: number | null
}

export const toRem = (value: number) => `${value}rem`

export const getTableMinWidth = (columns: TableColumn[], minTextColumnRem: number, extraRem: number) => {
  let total = extraRem
  for (const column of columns) {
    total += column.widthRem ?? minTextColumnRem
  }
  return toRem(total)
}
