# Política de dados e publicação

## Regra do projeto
O Portal Fatos Públicos deve versionar apenas informações necessárias ao funcionamento do portal e obtidas de fontes públicas verificáveis.

## Pode ser publicado
- dados oficiais de candidaturas e eleições;
- votos e atos legislativos publicados por Câmara/Senado;
- emendas e execução orçamentária publicadas em portais oficiais;
- patrimônio declarado oficialmente à Justiça Eleitoral;
- receitas e despesas eleitorais publicadas pelo TSE;
- nomes de fornecedores e beneficiários quando necessários para explicar registros públicos.

## Não deve ser publicado
- senhas;
- tokens;
- chaves de API;
- cookies ou sessões;
- credenciais de GitHub;
- e-mails, telefones ou dados pessoais dos responsáveis pelo projeto sem necessidade;
- caminhos locais do computador;
- arquivos `.env`;
- chaves privadas;
- CPF de pessoa física quando não for indispensável para a finalidade do portal.

## Minimização aplicada antes do primeiro GitHub
A versão preparada para publicação removeu os campos de CPF/CNPJ da base financeira, pois esses identificadores não são necessários para a interface nesta etapa.

## Segredos futuros
Se alguma API vier a exigir credencial, ela deverá ser configurada como GitHub Actions Secret e jamais escrita no código ou nos arquivos de dados.
