python run_mminforec.py --lr=0.001 --weight_decay=1e-1 --pred_step=1 --tau=3 --data_name=Yelp --num_hidden_layers=1 --num_attention_heads=1 --attention_probs_dropout_prob=0.5 --hidden_dropout_prob=0.5 --dc_s=1 --dc=1 --num_hidden_layers_gru=1 --mem=64 --mil=4 --epoch=50 --loss_fuse_dropout_prob=0.5