import { memo } from 'react';
import type { Company } from '@/api/types';

const CompanyRow = ({ company }: { company: Company }) => {
  return (
    <tr>
      <td>{company.companyId}</td>
      <td>{company.companyName}</td>
      <td>{company.companyInn}</td>
      <td>{company.legalForm}</td>
      <td>{company.industry}</td>
    </tr>
  )
}

export default memo(CompanyRow)
