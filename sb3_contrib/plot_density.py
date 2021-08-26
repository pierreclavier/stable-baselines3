import numpy as np

import seaborn as sns
from matplotlib import pyplot as plt
sns.set()




import pandas as pd
df1=pd.read_csv('Points/state_tensor([22], dtype=torch.int32)_action_26_varpenal_False.csv', sep=',',header=None).values
df2=pd.read_csv('Points/state_tensor([22], dtype=torch.int32)_action_29_varpenal_False.csv', sep=',',header=None).values

df3=pd.read_csv('Points/state_tensor([22], dtype=torch.int32)_action_29_varpenal_True.csv', sep=',',header=None).values
df4=pd.read_csv('Points/state_tensor([22], dtype=torch.int32)_action_26_varpenal_True.csv', sep=',',header=None).values


df=[df1,df2,df3,df4]


nb_graphs=2
fig, axes = plt.subplots(1, np.int(nb_graphs)  , figsize=(15, 5), sharey=True)
fig.suptitle('Distribution of returns for state {}'.format(22))

for count,points in df :
    #print(action)




    sns.distplot(points, hist = False, kde = True, rug = True,
        color = 'darkblue',
        kde_kws={'linewidth': 3},
        rug_kws={'color': 'black'} ,ax=axes[count])

    #axes[count].set_title("action {}, var {}".format())

plot.legend()
plt.show()
